"""Stage-v2: public extension contracts, compositional controls and real faulty starters.

These are required candidate gates, distinct from the unchanged v0.1 compatibility probes.
An absent extension is a capability gap, never evidence that an old algorithm failed.
"""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import random
import tempfile

HERE=Path(__file__).resolve().parent
REQUIRED={
    'C1':('Ledger',['open_account','migrate','transfer','snapshot']),
    'C2':('BuildService',['set_graph','enqueue','cancel','run','get']),
    'C3':('GenerationStore',['commit','snapshot','prepare_compaction','migrate_writer','publish_compaction']),
    'C4':('VersionedBuilder',['update','activate','build']),
}


class LostReply(RuntimeError):pass


def require(actual,expected,reason):
    if actual!=expected:raise AssertionError(json.dumps(dict(reason=reason,expected=expected,actual=actual),ensure_ascii=False))


def c1(module,root,mode,seed):
    rng=random.Random(seed);amount=rng.randrange(2,30);balance=amount*10;ledger=module.Ledger(root)
    ledger.open_account('source',balance);ledger.open_account('target',0);fired=[]
    def disconnect(phase):
        require(phase,'after_commit','public hook phase');fired.append(phase);raise LostReply('receipt committed, network response lost')
    if mode=='migration_only':ledger.migrate('source');ledger.migrate('target')
    if mode in ('lost_reply_only','composition'):
        try:ledger.transfer('logical-1','source','target',amount,hook=disconnect)
        except LostReply:pass
        require(len(fired),1,'fault hook was not exercised')
    if mode=='composition':
        for _ in range(1+seed%3):ledger.migrate('source')
        ledger.migrate('target');ledger=module.Ledger(root)
    receipt=ledger.transfer('logical-1','source','target',amount)
    expected={'source':balance-amount,'target':amount}
    require(ledger.snapshot(),expected,'logical request duplicated after physical epoch migration')
    require(receipt,{'txid':'logical-1','amount':amount},'receipt identity changed')
    conflict=False
    try:ledger.transfer('logical-1','source','target',amount+1)
    except (ValueError,RuntimeError):conflict=True
    require(conflict,True,'same logical id accepted a different transfer')
    require(module.Ledger(root).snapshot(),expected,'reopened ledger lost balances')
    return dict(balance=balance,amount=amount,expected=expected,receipt=receipt,reopened=True)


def c2(module,root,mode,seed):
    a=seed%19+2;b=seed%11+3;old={'inputs':[a,b],'factor':2};new={'inputs':[a+7,b+13],'factor':3}
    service=module.BuildService(root);service.set_graph('P',old);job=service.enqueue('P');fired=[]
    def cancel(phase):
        require(phase,'after_prepare','public hook phase');fired.append(phase)
        # A second handle simulates the API cancelling while a worker owns prepared work.
        module.BuildService(root).cancel(job)
    if mode in ('cancel_only','composition'):
        result=service.run(job,hook=cancel);require(result['status'],'cancelled','cancelled work was published')
        require(len(fired),1,'cancellation hook was not exercised')
    else:
        result=service.run(job);require(result['value'],sum(old['inputs'])*2,'first build incorrect')
    if mode in ('revision_only','composition'):revision=service.set_graph('P',new);expected=sum(new['inputs'])*3
    else:revision=0;expected=sum(old['inputs'])*2
    # Recreate the worker after cancellation; stale recovery artifacts are persistent.
    service=module.BuildService(root);retry=service.enqueue('P');result=service.run(retry)
    require(result['status'],'done','retry failed');require(result['value'],expected,'cancelled prior generation artifact poisoned new graph')
    require(result['revision'],revision,'retry receipt has the wrong immutable graph identity')
    if mode in ('cancel_only','composition'):require(service.get(job)['status'],'cancelled','old cancellation changed during retry')
    require(module.BuildService(root).get(retry)['value'],expected,'published retry did not survive reopen')
    return dict(old_value=sum(old['inputs'])*2,expected=expected,retry=result)


def c3(module,root,mode,seed):
    store=module.GenerationStore(root);value=str(seed);v1=store.commit('a',{'stable':value,'deleted':'old'})
    frozen=store.snapshot();token=store.prepare_compaction()
    if mode=='compaction_only':store.publish_compaction(token)
    else:store.migrate_writer()
    current=module.GenerationStore(root)
    if mode!='compaction_only':v2=current.commit('b',{'new':value+'-new','deleted':None})
    else:v2=None
    if mode=='composition':
        try:store.publish_compaction(token)
        except RuntimeError:pass  # Explicit stale-generation rejection is a correct outcome.
    expected={'stable':value,'deleted':'old'} if mode=='compaction_only' else {'stable':value,'new':value+'-new'}
    reopened=module.GenerationStore(root);require(reopened.snapshot(),expected,'old-generation compaction erased a new-generation ACK or resurrected a tombstone')
    require(frozen,{'stable':value,'deleted':'old'},'old read snapshot mutated')
    require(reopened.commit('a',{'stable':value,'deleted':'old'}),v1,'old transaction replay changed version')
    if v2 is not None:require(reopened.commit('b',{'new':value+'-new','deleted':None}),v2,'new transaction receipt lost')
    require(reopened.snapshot(),expected,'idempotent replay changed state after migration')
    return dict(expected=expected,first_version=v1,second_version=v2,snapshot_frozen=True)


def c4(module,root,mode,seed):
    builder=module.VersionedBuilder(root);prefix=str(seed)
    old_sources={'a':prefix+'-a','b':prefix+'-b'};old_env={'BUILD':'old'}
    new_sources={'a':prefix+'-new-a','b':prefix+'-new-b'};new_env={'BUILD':'new'}
    def output(sources,env):return '|'.join(sources[k] for k in sorted(sources))+'#'+'|'.join(str(env[k]) for k in sorted(env))
    v1=builder.update(old_sources,old_env);expected={v1:output(old_sources,old_env)};fired=[]
    if mode=='update_only':v2=builder.update(new_sources,new_env);expected[v2]=output(new_sources,new_env)
    def replace(phase):
        require(phase,'after_sources','public hook phase');fired.append(phase)
        v2=module.VersionedBuilder(root).update(new_sources,new_env);expected[v2]=output(new_sources,new_env)
    try:result=builder.build(hook=replace if mode=='composition' else None)
    except Exception as exc:
        retry_type=getattr(module,'RetryRequired',None)
        if retry_type is None or not isinstance(exc,retry_type):raise
        result=builder.build()
    if mode=='composition':require(len(fired),1,'concurrent manifest hook was not exercised')
    require(result.get('version') in expected,True,'build did not identify a visible immutable manifest')
    require(result['data'],expected[result['version']],'sources and environment came from different manifest generations')
    # Whatever the successful cut, old manifest builds must not find poisoned shared cache.
    builder=module.VersionedBuilder(root);builder.activate(v1);replayed=builder.build()
    require(replayed,{'version':v1,'data':expected[v1]},'a mixed cut was cached under an immutable old manifest')
    return dict(visible_versions=len(expected),consistent_result=result,old_manifest_replayed=True)


CONTROLS={'C1':['lost_reply_only','migration_only'],'C2':['cancel_only','revision_only'],
          'C3':['compaction_only','migration_only'],'C4':['stable_only','update_only']}


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def evaluate_module(task,path,scale,seed):
    if path is None or not Path(path).is_file():
        return dict(status='capability_gap',valid=False,path=str(path) if path else None,
                    reason='required stage-v2 module extreme.py is absent',checks=[])
    try:
        module=load(path,'stage_'+task);cls,methods=REQUIRED[task]
        if not hasattr(module,cls) or any(not hasattr(getattr(module,cls),method) for method in methods):
            return dict(status='capability_gap',valid=False,reason='required '+cls+' methods missing',checks=[])
    except Exception as exc:return dict(status='import_error',valid=False,reason=type(exc).__name__+': '+str(exc),checks=[])
    checks=[]
    modes=CONTROLS[task]+['composition']*(12 if scale=='full' else 1)
    with tempfile.TemporaryDirectory(prefix=task+'-protocol-') as directory:
        for i,mode in enumerate(modes):
            root=Path(directory)/str(i);root.mkdir()
            try:
                # Keep both isolated controls at the same data as the first composition.
                # Subsequent full cases vary the data, not the mechanism semantics.
                evidence=globals()[task.lower()](module,root,mode,seed+max(0,i-2))
                checks.append(dict(name=mode,index=i,passed=True,evidence=evidence))
            except Exception as exc:checks.append(dict(name=mode,index=i,passed=False,error=type(exc).__name__+': '+str(exc)[:1800]))
    return dict(status='passed' if all(c['passed'] for c in checks) else 'behavior_failure',
                valid=all(c['passed'] for c in checks),path=str(path),checks=checks,
                controls_passed=all(c['passed'] for c in checks if c['name']!='composition'),
                composition_passed=all(c['passed'] for c in checks if c['name']=='composition'))


def tiny_witness(task):
    """Explicit feasible histories, not a general extreme candidate implementation."""
    witnesses={
        'C1':dict(initial={'a':100,'b':0},after_transfer={'a':90,'b':10},after_migration_and_retry={'a':90,'b':10},
                  legal_strategy='receipt identity stays (logical source, request id) across physical epochs'),
        'C2':dict(old_graph_value=(2+3)*2,new_graph_value=(9+16)*3,cancelled_value=None,
                  legal_strategy='recovery artifact includes immutable graph revision; discard or recompute mismatches'),
        'C3':dict(old_snapshot={'a':1,'deleted':3},new_acknowledged={'a':1,'b':2},after_old_publish={'a':1,'b':2},
                  legal_strategy='compare captured writer epoch and content version before publishing; reject obsolete token'),
        'C4':dict(visible_manifests={'old':'old-a|old-b#old','new':'new-a|new-b#new'},illegal_mix='old-a|old-b#new',
                  legal_strategy='pin complete immutable manifest or report RetryRequired before publishing any cache entry'),
    }
    value=witnesses[task]
    # Independently execute the small mathematical history, rather than merely
    # asserting that a literal equals itself. This is not an I/O implementation.
    expected={'C1':value.get('after_transfer'),'C2':value.get('new_graph_value'),
              'C3':value.get('new_acknowledged'),'C4':value.get('visible_manifests')}[task]
    if task=='C1':
        observed=dict(value['initial']);seen=set()
        for epoch in (0,1):
            if 'request-1' not in seen:observed['a']-=10;observed['b']+=10;seen.add('request-1')
    elif task=='C2':
        recovery={'revision':0,'value':(2+3)*2};current_revision=1
        observed=recovery['value'] if recovery['revision']==current_revision else sum([9,16])*3
    elif task=='C3':
        observed=dict(value['old_snapshot']);token=dict(epoch=0,data=dict(observed));current_epoch=1
        observed.pop('deleted');observed['b']=2
        if token['epoch']==current_epoch:observed=token['data']
    else:
        observed={version:'|'.join([version+'-a',version+'-b'])+'#'+version for version in ('old','new')}
    require(observed,expected,'independently executed finite witness')
    rejected=False
    try:require({'corrupt':True},expected,'negative witness')
    except AssertionError:rejected=True
    assert rejected
    return dict(feasible=True,kind='finite_trace_witness_not_complete_solver',
                execution='independent finite-state arithmetic, not a complete I/O implementation',
                trace=value,negative_perturbation_rejected=True)


def run(task,submission,scale,seed):
    path=Path(submission);extension=(path if path.is_dir() else path.parent)/'extreme.py'
    candidate=evaluate_module(task,extension,scale,seed)
    negative=evaluate_module(task,HERE/task/'extreme'/'starter.py','smoke',seed)
    # Audit must see the two local mechanisms work, then the composition fail for real.
    audit=(negative.get('controls_passed') is True and negative.get('composition_passed') is False
           and any(not c['passed'] and c['name']=='composition' for c in negative['checks']))
    return dict(contract='stage-v2',required=True,candidate=candidate,faulty_starter=negative,
                tiny_feasible_witness=tiny_witness(task),audit_passed=audit,
                difficulty_evidence='same runnable starter passes isolated controls but fails their composition; not an impossibility proof')
