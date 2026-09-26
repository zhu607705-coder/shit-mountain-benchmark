from __future__ import annotations
import json,os,random,tempfile,time,subprocess,sys,importlib.util,zlib,select
from pathlib import Path


def evaluate(mod):
    results=[]
    def check(name,fn):
        try:fn();results.append({'name':name,'pass':True})
        except Exception as e:results.append({'name':name,'pass':False,'error':repr(e)})
    def put(k,v):return {'op':'put','key':k,'value':v}
    def basic():
        with tempfile.TemporaryDirectory() as d:
            with mod.Store(d) as s:
                assert s.commit('a',[put('甲','一'),put('b','2')])==1
                assert s.get('甲')=='一';s.commit('b',[{'op':'del','key':'b'}]);assert s.get('b') is None
    def snapshot():
        with tempfile.TemporaryDirectory() as d:
            with mod.Store(d) as s:
                s.commit('a',[put('c','1'),put('a','2')]);p=s.snapshot()
                s.commit('b',[put('c','3'),put('b','4')]);assert p.scan()==[('a','2'),('c','1')]
    def invalid():
        with tempfile.TemporaryDirectory() as d:
            with mod.Store(d) as s:
                try:s.commit('x',[put('key','v'),{'op':'bad','key':'other'}])
                except ValueError:pass
                else:raise AssertionError('invalid accepted')
                assert s.get('key') is None and s.version==0
    def retry():
        with tempfile.TemporaryDirectory() as d:
            with mod.Store(d) as s:s.commit('x',[put('a','v')]);s.compact()
            with mod.Store(d) as s:
                assert s.commit('x',[put('a','v')])==1
                try:s.commit('x',[put('a','other')])
                except ValueError:pass
                else:raise AssertionError('conflicting id accepted')
    def delete():
        with tempfile.TemporaryDirectory() as d:
            with mod.Store(d) as s:
                s.commit('x',[put('a','v')]);s.commit('y',[{'op':'del','key':'a'}]);s.compact()
            with mod.Store(d) as s:assert s.get('a') is None and s.version==2
    def locking():
        with tempfile.TemporaryDirectory() as d:
            with mod.Store(d) as s:
                try:other=mod.Store(d)
                except mod.AlreadyOpen:pass
                else:other.close();raise AssertionError('two writers')
    def process_locking():
        code='''import importlib.util,sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).resolve().parent))
s=importlib.util.spec_from_file_location("candidate",sys.argv[1]);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
try:k=m.Store(sys.argv[2])
except m.AlreadyOpen:sys.exit(0)
else:k.close();sys.exit(3)
'''
        with tempfile.TemporaryDirectory() as d:
            with mod.Store(d):
                result=subprocess.run([sys.executable,'-c',code,mod.__file__,d],capture_output=True,text=True,timeout=5)
                assert result.returncode==0,('subprocess accepted second writer',result.stderr)
    def changed_cwd():
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as d:
            try:
                os.chdir(d)
                with mod.Store('数据库 空格') as s:
                    s.commit('a',[put('stable','yes')]);Path('elsewhere').mkdir();os.chdir('elsewhere')
                    s.compact();assert s.get('stable')=='yes'
                os.chdir(d)
                with mod.Store('数据库 空格') as s:assert s.get('stable')=='yes'
            finally:os.chdir(previous)
    def randomized():
        r=random.Random(182);expected={}
        with tempfile.TemporaryDirectory() as d:
            for cycle in range(5):
                with mod.Store(d) as s:
                    for i in range(40):
                        ops=[]
                        for _ in range(r.randint(1,5)):
                            k='k'+str(r.randrange(30))
                            if r.random()<.75:
                                v=str(r.randrange(10000));ops.append(put(k,v));expected[k]=v
                            else:ops.append({'op':'del','key':k});expected.pop(k,None)
                        s.commit(f'{cycle}:{i}',ops)
                        assert dict(s.snapshot().scan())==expected
                    s.compact()
    # Black-box process death. Parent writes only acknowledged stable prefix;
    # child writes one large transaction and is killed during/after execution.
    def killed_transaction():
        code='''import importlib.util,sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).resolve().parent))
s=importlib.util.spec_from_file_location("candidate",sys.argv[1]);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
k=m.Store(sys.argv[2]);print("READY",flush=True)
k.commit("bulk",[{"op":"put","key":"b"+str(i),"value":"x"*16384} for i in range(512)])
print("ACK",flush=True)
'''
        for delay in (0,.001,.01,.04):
            with tempfile.TemporaryDirectory() as d:
                with mod.Store(d) as s:s.commit('prefix',[put('stable','yes')])
                p=subprocess.Popen([sys.executable,'-c',code,mod.__file__,d],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    assert select.select([p.stdout],[],[],5)[0], 'child READY timeout'
                    assert p.stdout.readline().strip()=='READY'
                    time.sleep(delay);p.kill();out,_=p.communicate(timeout=5)
                finally:
                    if p.poll() is None:p.kill()
                    p.communicate(timeout=5)
                with mod.Store(d) as s:
                    assert s.get('stable')=='yes';n=len(s.snapshot().scan('b'));assert n in (0,512),n
                    if 'ACK' in out.splitlines():assert n==512,'acknowledged bulk transaction lost'
                    s.commit('after',[put('z','ok')])
    def ack_durable():
        code='''import importlib.util,sys,os
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).resolve().parent))
s=importlib.util.spec_from_file_location("candidate",sys.argv[1]);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
k=m.Store(sys.argv[2]);k.commit("ack",[{"op":"put","key":"ack","value":"saved"}]);os._exit(0)
'''
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable,'-c',code,mod.__file__,d],check=True,timeout=10)
            with mod.Store(d) as s:assert s.get('ack')=='saved'
    def closed():
        with tempfile.TemporaryDirectory() as d:
            s=mod.Store(d);s.close()
            try:s.commit('x',[put('a','b')])
            except RuntimeError:pass
            else:raise AssertionError('write after close')
    for name,fn in [('basic',basic),('immutable_snapshot',snapshot),('atomic_validation',invalid),('idempotency_after_compact',retry),('delete_no_resurrection',delete),('single_writer',locking),('single_writer_subprocess',process_locking),('relative_path_after_cwd_change',changed_cwd),('random_model_200_transactions',randomized),('sigkill_atomicity_4_windows',killed_transaction),('acknowledged_process_exit',ack_durable),('closed_handle',closed)]:check(name,fn)
    # Format-specific diagnostic only. It is not part of the public generic scoring.
    internal=[]
    if getattr(mod,'BASELINE_FORMAT_DIAGNOSTICS',False):
        for suffix in (b'\x00\x00',mod.HEADER.pack(100,0)+b'abc'):
            with tempfile.TemporaryDirectory() as d:
                with mod.Store(d) as s:s.commit('a',[put('stable','yes')])
                with open(Path(d)/'data.wal','ab') as f:f.write(suffix)
                with mod.Store(d) as s:assert s.get('stable')=='yes';s.commit('b',[put('next','yes')])
            internal.append(True)
        with tempfile.TemporaryDirectory() as d:
            with mod.Store(d) as s:s.commit('a',[put('stable','yes')])
            path=Path(d)/'data.wal';b=bytearray(path.read_bytes());b[-1]^=1;path.write_bytes(b)
            try:mod.Store(d)
            except mod.CorruptionError:internal.append(True)
            else:internal.append(False)
    with tempfile.TemporaryDirectory() as d:
        t=time.perf_counter()
        with mod.Store(d) as s:
            for i in range(500):s.commit(str(i),[put('key-'+str(i),'v'*100)])
        elapsed=time.perf_counter()-t
    return {'checks_passed':sum(x['pass'] for x in results),'checks_total':len(results),'checks':results,
            'baseline_internal_format_checks':internal,'transactions_per_second_500':500/elapsed,
            'timing_seconds':elapsed,'timing_note':'single local run; not power-loss proof or formal leaderboard'}
