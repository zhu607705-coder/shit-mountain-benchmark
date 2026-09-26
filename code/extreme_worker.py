#!/usr/bin/env python3
"""Isolated evaluator driver; all child processes cleaned in parent finally blocks."""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from extreme import PROFILE, VERSION, dimensions
from extreme_scenarios import scenario, tiny_witnesses, vector_reference, bytes_reference, ledger_event, file_graph
from extreme_protocol import run as stage_run

HERE=Path(__file__).resolve().parent


def load(path,name):
    sys.path.insert(0,str(Path(path).resolve().parent))
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def candidate_file(path):
    if path.is_file():return path
    for name in ('engine.py','baseline.py','store.py'):
        if (path/name).is_file():return path/name
    raise FileNotFoundError('candidate must export engine.py, baseline.py or store.py')


def wait(predicate,timeout=8):
    end=time.monotonic()+timeout;last=None
    while time.monotonic()<end:
        try:
            last=predicate()
            if last:return last
        except (OSError,KeyError) as exc:last=str(exc)
        time.sleep(.02)
    raise AssertionError('deadline waiting for state: '+str(last))


class Checks:
    def __init__(self):self.rows=[]
    def run(self,name,fn,kind='interaction',critical=True):
        start=time.monotonic()
        try:
            detail=fn()
            self.rows.append(dict(name=name,passed=True,kind=kind,critical=critical,
                                  seconds=round(time.monotonic()-start,4),evidence=detail))
            return detail
        except Exception as exc:
            self.rows.append(dict(name=name,passed=False,kind=kind,critical=critical,
                                  seconds=round(time.monotonic()-start,4),
                                  error=type(exc).__name__+': '+str(exc)[:1800],
                                  classification='capability_gap' if isinstance(exc,CapabilityGap) else 'behavior_failure'))
            return None


class CapabilityGap(RuntimeError):pass


def c1(submission,case,checks):
    old=load(HERE/'C1'/'e2e_env_judge.py','ledger_env')
    oracle=load(HERE/'C1'/'oracle.py','ledger_reference')
    p=case['parameters'];accepted=[];observed=dict(http_requests=0,workers_started=0)
    with tempfile.TemporaryDirectory(prefix='c1-extreme-') as td:
        env=old.Environment(submission,td,relative=True,legacy=True)
        def request(method,path,body=None):
            data=None if body is None else json.dumps(body).encode()
            req=urllib.request.Request(f'http://127.0.0.1:{env.port}{path}',data=data,method=method,
                                       headers={'Content-Type':'application/json'})
            try:
                with env._http.open(req,timeout=8) as response:return response.status,json.load(response)
            except urllib.error.HTTPError as exc:return exc.code,json.loads(exc.read())
        env.request=request
        def start(role,delay='0'):
            process=env.start(role,delay)
            if role=='worker':observed['workers_started']+=1
            return process
        try:
            # Three real initializers race on the same v1 file; all must preserve it.
            initters=[]
            for _ in range(3):
                proc=subprocess.Popen([sys.executable,'-B',str(env.repo/'manage.py'),'init'],
                                      cwd=env.root,env=env.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                env.processes.append(proc);initters.append(proc)
            def migration():
                for proc in initters:assert proc.wait(timeout=5)==0,'concurrent migration failed'
                return dict(concurrent_migrators=len(initters),legacy_database=True)
            checks.run('concurrent_legacy_migration',migration)
            start('serve')
            assert env.request('GET','/v1/jobs/1?tenant=A')[1]['request_id']=='old'
            def recovery_chain():
                body=dict(tenant='R',request_id='lost-reply',events=[ledger_event('R','p0',31),
                    dict(tenant='R',id='reverse-future',kind='reverse',target='p1')])
                raw=json.dumps(body).encode()
                # Real HTTP request fully sent; client deliberately discards the response.
                with socket.create_connection(('127.0.0.1',env.port),timeout=2) as sock:
                    sock.sendall((f'POST /v1/batches HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\n\r\n').encode()+raw)
                    sock.shutdown(socket.SHUT_WR)
                wait(lambda:len(env.request('GET','/v1/jobs?tenant=R')[1]['jobs'])==1)
                receipt=env.submit(**body);assert receipt['duplicate'] is True,receipt
                accepted.extend(body['events'])
                slow=start('worker','0.7')
                # The legacy job may be claimed first; wait for the receipt's own claim.
                wait(lambda:env.request('GET',f'/v1/jobs/{receipt["job_id"]}?tenant=R')[1]['status']=='processing')
                slow.send_signal(signal.SIGSTOP);time.sleep(.16)
                rescue=start('worker')
                late=dict(tenant='R',request_id='after-steal',events=[ledger_event('R','p1',47),ledger_event('R','p0',32)])
                newer=env.submit(**late);accepted.extend(late['events'])
                wait(lambda:env.request('GET',f'/v1/jobs/{newer["job_id"]}?tenant=R')[1]['status']=='done')
                before=env.state('R');slow.send_signal(signal.SIGCONT);time.sleep(.75)
                after=env.state('R');expected=oracle.solve(accepted)
                assert {k:after[k] for k in expected}==expected,(after,expected)
                assert after['generation']>=before['generation'],(before,after)
                env.submit('R','lost-reply',[ledger_event('R','p0',999)],expected=409)
                assert env.submit(**body)['job_id']==receipt['job_id']
                assert env.request('GET',f'/v1/jobs/{receipt["job_id"]}?tenant=other')[0]==404
                return dict(lost_response_replayed=True,lease_stolen=True,old_worker_resumed=True,
                            late_conflict_and_reverse=expected['statuses'],generation=after['generation'])
            checks.run('migration_lost_ack_lease_steal_late_conflict',recovery_chain)
            # Stop delay-injected workers before the quantitative workload.
            for proc in list(env.processes):
                if proc.args[-1]=='worker':
                    try:proc.send_signal(signal.SIGCONT)
                    except ProcessLookupError:pass
                    env.stop(proc)
            def workload():
                for _ in range(p['workers']):start('worker')
                observed['workers']=p['workers']
                jobs=[];by_tenant={}
                def submit(batch):return batch,env.submit(**batch)['job_id']
                # Each epoch is a barrier; worker scheduling inside epochs remains concurrent.
                for r in range(p['rounds']):
                    group=case['batches'][r*p['tenants']:(r+1)*p['tenants']]
                    calls=[group[i%len(group)] for i in range(max(len(group),p['http_concurrency']))]
                    received={}
                    with concurrent.futures.ThreadPoolExecutor(max_workers=p['http_concurrency']) as pool:
                        for batch,jid in pool.map(submit,calls):
                            key=batch['tenant'],batch['request_id']
                            if key in received:assert received[key][1]==jid,'same-key race produced two receipts'
                            received[key]=(batch,jid)
                    for batch,jid in received.values():
                        assert env.submit(**batch)['job_id']==jid
                        jobs.append((batch['tenant'],jid));by_tenant.setdefault(batch['tenant'],[]).extend(batch['events'])
                    observed['http_requests']+=len(calls)+len(received)
                    observed['http_concurrency']=min(len(calls),p['http_concurrency'])
                wait(lambda:all(env.request('GET',f'/v1/jobs/{jid}?tenant={tenant}')[1]['status']=='done'
                                for tenant,jid in jobs),timeout=180 if case['scale']=='full' else 8)
                for tenant,events in by_tenant.items():
                    state=env.state(tenant);expected=oracle.solve(events)
                    assert {k:state[k] for k in expected}==expected,(tenant,state,expected)
                    stats=env.request('GET',f'/v1/stats?tenant={tenant}')[1]
                    assert stats['jobs']==p['rounds'] and stats['done']==p['rounds'],stats
                observed.update(tenants=len(by_tenant),batches=len(jobs),events=sum(map(len,by_tenant.values())))
                # Real complete service restart; replay must return the same receipt.
                for proc in list(env.processes):env.stop(proc)
                start('serve');start('worker')
                batch=case['batches'][-1];replay=env.submit(**batch)
                assert replay['duplicate'] is True
                assert env.state(batch['tenant'])['statuses']==oracle.solve(by_tenant[batch['tenant']])['statuses']
                return observed
            checks.run('epoch_replay_isolation_projection_restart',workload)
            if not checks.rows[-1]['passed']:
                checks.rows[-1]['service_log_tail']={name:tail for name,tail in env.tail().items() if name.startswith('serve')}
        finally:
            for proc in env.processes:
                if proc.poll() is None:
                    try:proc.send_signal(signal.SIGCONT)
                    except ProcessLookupError:pass
            env.close()
    return observed


def c2(submission,case,checks):
    old=load(HERE/'C2'/'e2e_env_judge.py','build_env');p=case['parameters'];observed={}
    env=old.Stack(submission,prefix='/extreme/build',split=True,unicode=True,legacy=True,delay=.10)
    try:
        env.start('serve')
        def history():
            queued=[]
            for item in case['revisions']:
                pid=item['project'];spec=item['graph'];env.ok('/projects/'+pid,spec)
                jid=env.enqueue(pid)
                queued.append((pid,jid,vector_reference(spec,'main')))
                # Mutating the alias in a NEW revision cannot change the queued graph.
                changed=json.loads(json.dumps(spec));changed['aliases']['main']='n0'
                env.ok('/projects/'+pid+'/graph',changed)
            # Cancel jobs while pending, after graph replacement, then restart workers.
            cancelled=set()
            for i,(pid,jid,_) in enumerate(queued):
                if i%4==0:env.ok(f'/projects/{pid}/jobs/{jid}/cancel',{});cancelled.add(jid)
            for _ in range(p['workers']):env.start('worker')
            running=next((pid,jid,values) for pid,jid,values in queued if jid not in cancelled)
            # Cancel after running has become observable, then abruptly lose that worker.
            pid,jid,_=running
            current=env.wait(pid,jid,statuses={'running','done','failed'},timeout=8)
            if current['status']=='running':
                env.ok(f'/projects/{pid}/jobs/{jid}/cancel',{});cancelled.add(jid)
            env.stop(env.worker,kill=True);env.start('worker')
            for pid,jid,expected in queued:
                result=env.wait(pid,jid,timeout=80 if case['scale']=='full' else 8)
                if jid in cancelled:assert result['status']=='cancelled',result
                else:assert result['status']=='done' and result['result']=={'value':expected},(result,expected)
                assert env.request(f'/projects/other/jobs/{jid}')[0]==404
            # A retry targets the NEW graph and must not inherit the old cancellation/cache.
            retries=[]
            for i in range(p['projects']):
                pid='P'+str(i);jid=env.enqueue(pid);item=[x for x in case['revisions'] if x['project']==pid][-1]
                expected=item['graph']['nodes']['n0']['data'];env.done(pid,jid,expected);retries.append(jid)
            env.stop(env.server);env.start('serve')
            for i,jid in enumerate(retries):assert env.ok(f'/projects/P{i}/jobs/{jid}')['status']=='done'
            observed.update(queued_snapshots=len(queued),cancelled=len(cancelled),projects=p['projects'],retries=len(retries))
            return dict(**observed,graph_updates=len(queued)*2,restart=True,multiworker=True)
        checks.run('snapshot_alias_cancel_worker_loss_retry_restart',history)
        def deep():
            spec=case['deep_graph'];expected=vector_reference(spec,'main')
            env.ok('/projects/deep',spec);jid=env.enqueue('deep')
            result=env.wait('deep',jid,timeout=60 if case['scale']=='full' else 8)
            observed.update(nodes=len(spec['nodes']),depth=p['depth'])
            assert result['status']=='done' and result['result']=={'value':expected},dict(actual=result,expected=expected)
            return dict(nodes=len(spec['nodes']),depth=p['depth'],expected=expected)
        checks.run('deep_shared_dag_scale_boundary',deep,kind='scale_boundary')
    finally:env.close()
    return observed


def run_file_probe(submission,root,mode,extra=None,timeout=8):
    cmd=[sys.executable,'-B',str(HERE/'extreme_fault_probe.py'),'--submission',str(submission),
         '--root',str(root),'--mode',mode]
    if extra:
        argument_file=Path(root).parent/(Path(root).name+'-'+mode+'-arguments.json')
        argument_file.write_text(json.dumps(extra))
        cmd.extend(['--arguments-file',str(argument_file)])
    proc=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
    try:payload=json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    except ValueError:payload={}
    return proc.returncode,payload,proc.stderr[-1500:]


def c3(submission,case,checks):
    module=candidate_file(submission);p=case['parameters'];observed=dict(injected=0,not_intercepted=0)
    with tempfile.TemporaryDirectory(prefix='c3-extreme-') as td:
        base=Path(td)
        # Complete API contract witness on actual files, independent from fault schedule.
        def live_history():
            code,result,error=run_file_probe(module,base/'live','store_history',
                                            dict(records=case['initial_records'],transactions=case['transactions'],readers=p['snapshot_readers']),
                                            timeout=180 if case['scale']=='full' else 12)
            assert code==0,(result,error)
            observed.update(result)
            return result
        checks.run('immutable_snapshot_compaction_idempotency_concurrent_readers',live_history)
        for index,item in enumerate(case['fault_schedule']):
            def probe(item=item,index=index):
                root=base/('cut-'+str(index));root.mkdir()
                code,result,error=run_file_probe(module,root,'store_fault',item,timeout=8)
                receipt=json.loads((root/'receipt.json').read_text())
                if not receipt.get('intercepted'):
                    observed['not_intercepted']+=1
                    raise CapabilityGap('I/O bypassed Python os interception; '+str(item)+' needs supported instrumentation, not counted as tested')
                observed['injected']+=1
                if item['mode']=='kill_after':assert code==-signal.SIGKILL,(code,result,error)
                else:assert code==0,(code,result,error)
                rc,after,stderr=run_file_probe(module,root,'store_recover',{},timeout=8)
                assert rc==0,(after,stderr)
                return dict(intercepted=True,cut=item,recovery=after)
            checks.run('fault_'+str(index)+'_'+item['cut']+'_'+item['mode'],probe,kind='fault_interaction')
        observed['fault_histories']=len(case['fault_schedule'])
    return observed


def c4(submission,case,checks):
    path=candidate_file(submission);candidate=load(path,'candidate_builder');p=case['parameters'];observed={}
    if not hasattr(candidate,'Builder'):raise AttributeError('capability error: Builder class is missing')
    with tempfile.TemporaryDirectory(prefix='c4-extreme-') as td:
        base=Path(td);cache=base/'cache';cache.mkdir();roots=[]
        for i in range(p['roots']):
            root=base/('project-'+str(i));root.mkdir();(root/'input.txt').write_bytes(f'{i:012d}'.encode());roots.append(root)
        spec=file_graph(12,4)
        def build(root,current_spec,env):
            expected=bytes_reference(current_spec,'root',{'input.txt':(root/'input.txt').read_bytes()},env)
            actual=candidate.Builder(root,cache).build(current_spec,'root',env)
            assert type(actual) is bytes and actual==expected,(actual,expected)
            return hashlib.sha256(actual).hexdigest()
        def histories():
            digests=[]
            for i,item in enumerate(case['histories']):
                root=roots[item['root']];source=root/'input.txt';old=source.stat();env=item['env']
                source.write_bytes(item['payload'].encode());os.utime(source,ns=(old.st_atime_ns,old.st_mtime_ns))
                current=json.loads(json.dumps(spec))
                if item['operation']=='order_change':current['nodes']['root']['deps'].reverse()
                if item['operation']=='delete_repair':
                    source.unlink()
                    try:candidate.Builder(root,cache).build(current,'root',env)
                    except Exception as exc:
                        assert isinstance(exc,candidate.BuildError),type(exc).__name__
                    else:raise AssertionError('missing source was hidden by a prior cache hit')
                    source.write_bytes(item['payload'].encode())
                if item['operation']=='publish_retry':
                    # Failed prior publishers can leave truncated entries. Corrupt only own cache.
                    # This is a documented format-neutral directory recovery exercise:
                    # a candidate may reject the damaged cache, but the retry must repair it.
                    for entry in list(cache.glob('*'))[:3]:
                        if entry.is_file():entry.write_bytes(b'{incomplete')
                digests.append(build(root,current,env))
            observed.update(mutations=len(case['histories']),roots=len(roots),distinct_outputs=len(set(digests)))
            return dict(**observed,same_mtime=True,dependency_order_changes=True,failed_build_retried=True)
        checks.run('cross_root_epoch_change_delete_repair_order_history',histories)
        def concurrent():
            config=base/'build-case.json';config.write_text(json.dumps(spec))
            processes=[]
            try:
                for i in range(p['parallel_publishers']):
                    root=roots[i%len(roots)]
                    args=dict(spec=str(config),cache=str(cache),env={'BUILD':str(i%3)})
                    cmd=[sys.executable,'-B',str(HERE/'extreme_fault_probe.py'),'--submission',str(path),
                         '--root',str(root),'--mode','builder','--arguments',json.dumps(args)]
                    processes.append((subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE),root,args['env']))
                outputs=[]
                for proc,root,env in processes:
                    stdout,stderr=proc.communicate(timeout=15)
                    assert proc.returncode==0,stderr.decode(errors='replace')[-1000:]
                    data=json.loads(stdout);expected=bytes_reference(spec,'root',{'input.txt':(root/'input.txt').read_bytes()},env)
                    assert data['hex']==expected.hex(),data;outputs.append(data['hex'])
                # A new source epoch after concurrent old publications must never reuse old data.
                for root in roots:(root/'input.txt').write_bytes(b'after-race!!')
                for root in roots:build(root,spec,{'BUILD':'after'})
                observed['parallel_publishers']=len(processes)
                return dict(processes=len(processes),distinct_outputs=len(set(outputs)),after_publication_epoch_verified=True)
            finally:
                for proc,_,_ in processes:
                    if proc.poll() is None:proc.kill();proc.wait(timeout=2)
                    for stream in (proc.stdout,proc.stderr):
                        if stream:stream.close()
        checks.run('concurrent_publish_then_new_epoch',concurrent)
        def deep():
            spec=case['deep_graph'];root=roots[0];expected=bytes_reference(spec,'root',{'input.txt':(root/'input.txt').read_bytes()},{'BUILD':'deep'})
            observed.update(nodes=len(spec['nodes']),depth=p['depth'])
            actual=candidate.Builder(root,cache).build(spec,'root',{'BUILD':'deep'})
            assert actual==expected,(actual,expected)
            return dict(nodes=len(spec['nodes']),depth=p['depth'],digest=hashlib.sha256(actual).hexdigest())
        checks.run('deep_shared_dag_scale_boundary',deep,kind='scale_boundary')
    return observed


MECHANISMS={
    'C1':['required stage-v2: logical transfer receipt + physical shard epoch migration + ACK-loss replay','migration + lost HTTP response + idempotent replay','lease takeover + stale worker resumption + late conflict/reversal','epoch barriers + tenant isolation + full restart'],
    'C2':['required stage-v2: cancelled prepared artifact + new immutable graph generation + reopened retry','queued immutable graph + alias revision + cancellation','multiple workers + abrupt worker loss + retry + service restart','shared DAG depth and size extension; scale boundary, not reasoning proof'],
    'C3':['required stage-v2: old prepared compaction + writer generation migration + new ACK/tombstone + late publication','acknowledged durable prefix + partial I/O + reopen','compaction publication + directory sync failure + transaction identity','immutable old snapshots + concurrent readers + post-failure retry'],
    'C4':['required stage-v2: manifest changes during build + consistent source/env cut + immutable cache publication','shared cache across roots + equal-mtime mutation + ordered dependencies','failed source build + repair + corrupted-cache retry','concurrent publication + subsequent source/environment epoch change','5000-node iterative-reference comparison; scale boundary, not reasoning proof'],
}


def machine_quality(checks):
    """Binary v0.2 contract quality; wall-clock/token efficiency is scored by the host."""
    required=[check for check in checks if check.get('critical',True)]
    return 100 if required and all(check.get('passed') is True for check in required) else 0


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--task',required=True);parser.add_argument('--scale',required=True)
    parser.add_argument('--seed',type=int,required=True);parser.add_argument('--submission',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();checks=Checks();case=scenario(args.task,args.scale,args.seed);witness=tiny_witnesses();observed={}
    try:observed=globals()[args.task.lower()](args.submission,case,checks)
    except Exception as exc:
        checks.rows.append(dict(name='candidate_startup',passed=False,kind='capability_or_startup',critical=True,error=type(exc).__name__+': '+str(exc)[:1800]))
    rows=checks.rows
    legacy=dict(checks=list(rows),valid=all(x['passed'] for x in rows if x['critical']))
    extension=stage_run(args.task,args.submission,args.scale,args.seed)
    stage=extension['candidate']
    if stage.get('checks'):
        for check in stage['checks']:
            rows.append(dict(check,name='stage_v2_'+check['name']+'_'+str(check['index']),
                             kind='new_contract_composition' if check['name']=='composition' else 'new_contract_control',critical=True))
    else:rows.append(dict(name='stage_v2_capability',passed=False,kind='capability_gap',critical=True,
                          classification='capability_gap',error=stage.get('reason')))
    passed=sum(x['passed'] for x in rows);quality=machine_quality(rows);critical=quality==100
    dims=dimensions(args.task,args.scale)
    for dim in dims:
        if dim['name'] in case['counts']:dim['scope']='generated'
        if dim['name'] in observed:dim['scope']='executed'
    result=dict(task_id=args.task,profile=PROFILE,version=VERSION,scale=args.scale,seed=args.seed,dimensions=dims,
        mechanisms=MECHANISMS[args.task],candidate_result=dict(valid=critical,status='passed' if critical else 'incomplete',
          legacy_probe=legacy,stage_v2=stage,
          checks_passed=passed,checks_total=len(rows),machine_pass_rate=passed/len(rows) if rows else 0,
          raw_score=quality,quality_score=quality,
          checks=rows,score_status='binary machine contract quality; independent host scores agent elapsed time and tokens'),
        verification=dict(executed=True,constructed=case['counts'],observed=observed,tiny_feasible_witness=witness,
                          negative_control_expected='C2/C4 old recursive baselines may fail depth; evaluated behavior is never hardcoded'),
        stage_v2=extension,audit_passed=extension['audit_passed'],limitations=['public seeded workloads; not hidden evaluation','local trusted-code runner, not a security sandbox',
          'judge execution time is diagnostic runtime, not model thinking time; agent elapsed time/tokens come from the independent host',
          'passing interaction chains is reported honestly; no claim that the author cannot solve a problem',
          'C3 intercepts Python os I/O calls; native/buffered I/O adapters require separate instrumentation; process kill is not power loss'])
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
