#!/usr/bin/env python3
"""Executable, source-compatible extended engineering challenges. Trusted local code."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
PROFILE = 'extreme'
VERSION = '0.2'


def parameters(task, scale):
    full = scale == 'full'
    return {
        'C1': dict(tenants=20 if full else 3, rounds=80 if full else 3,
                   events_per_batch=80 if full else 8, workers=20 if full else 2,
                   http_concurrency=80 if full else 8),
        'C2': dict(projects=20 if full else 3, revisions=20 if full else 3,
                   nodes=5000 if full else 1200, depth=2000 if full else 1100,
                   workers=4 if full else 2),
        'C3': dict(histories=12 if full else 1, cuts=6, fault_modes=4,
                   keys=100000 if full else 32, transactions=120 if full else 8,
                   snapshot_readers=8 if full else 2),
        'C4': dict(nodes=5000 if full else 1200, depth=2200 if full else 1100,
                   roots=20 if full else 2, mutations=1000 if full else 8,
                   parallel_publishers=12 if full else 3),
    }[task]


def dimensions(task, scale):
    # Denominators are named published workload facts, not alleged complexity proofs.
    entries = {
        'C1': [('tenants', 2, 20, 'C1/PROMPT.md: concurrent_isolation'),
               ('http_concurrency', 8, 80, 'C1/PROMPT.md: concurrent_isolation'),
               ('workers', 2, 20, 'C1/PROMPT.md: concurrent_isolation')],
        'C2': [('nodes', 500, 5000, 'C2/CORE_CONTRACT.md input limit'),
               ('depth', 200, 2000, 'C2/CORE_CONTRACT.md input limit')],
        'C3': [('fault_histories', 4, 288, 'C3/TASK.md: 4 kill windows; v0.2 = 12 histories x 6 cuts x 4 modes'),
               ('transactions', 200, 1440, 'C3/TASK.md: 200 random transactions; this axis is 7.2x, not 10x')],
        'C4': [('roots', 2, 20, 'C4/TASK.md: cache shared by two roots'),
               ('mutations', 100, 1000, 'C4/TASK.md: 100 random changes')],
    }[task]
    p = parameters(task, scale)
    if task == 'C3':
        p['fault_histories'] = p['histories'] * p['cuts'] * p['fault_modes']
        p['transactions'] *= p['histories']
    return [dict(name=name,legacy=old,current=p.get(name),ratio=p.get(name)/old,
                 scope='specified',full_target=new,full_target_ratio=new/old,
                 denominator_source=source) for name,old,new,source in entries]


def default_submission(task):
    return HERE/task/'repository'/'baseline' if task in ('C1','C2') else HERE/task/'baseline.py'


def export(task, scale, seed, destination):
    """Export an actual starter and materialized scenario, not an empty protocol."""
    from extreme_scenarios import scenario
    dest = Path(destination).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    starter = HERE/task/'repository'/'buggy' if task in ('C1','C2') else HERE/task/'starter'
    target = dest/'submission'
    if target.exists():
        raise FileExistsError('refuse to overwrite exported submission: '+str(target))
    shutil.copytree(starter, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(HERE/task/'extreme'/'starter.py',target/'extreme.py')
    payload = scenario(task, scale, seed)
    scenario_file = dest/'scenario.json'
    scenario_file.write_text(json.dumps(payload, ensure_ascii=False, separators=(',',':'))+'\n')
    shutil.copy2(HERE/task/'extreme'/'PROMPT.md', dest/'PROMPT.md')
    shutil.copy2(HERE/task/'extreme'/'STAGE_PROTOCOL.md',dest/'STAGE_PROTOCOL.md')
    contract = HERE/task/('CORE_CONTRACT.md' if task in ('C1','C2') else 'LEGACY_PROMPT.md')
    shutil.copy2(contract, dest/'COMPATIBILITY_CONTRACT.md')
    # Public export has no adjudicator, expected-result oracle or host witness.
    smoke='''#!/usr/bin/env python3
"""Public starter demonstration. Prints observations; does not assign benchmark scores."""
import importlib.util,json,tempfile
from pathlib import Path
root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('candidate_extension',root/'submission'/'extreme.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
with tempfile.TemporaryDirectory(prefix='public-demo-') as temporary:
    task=TASK
    if task=='C1':
        value=module.Ledger(temporary);value.open_account('a',100);value.open_account('b',0)
        result={'receipt':value.transfer('demo','a','b',10),'observed':value.snapshot()}
    elif task=='C2':
        value=module.BuildService(temporary);value.set_graph('demo',{'inputs':[2,3],'factor':2})
        result=value.run(value.enqueue('demo'))
    elif task=='C3':
        value=module.GenerationStore(temporary);version=value.commit('demo',{'key':'value'})
        result={'version':version,'observed':value.snapshot()}
    else:
        value=module.VersionedBuilder(temporary);value.update({'input':'hello'},{'BUILD':'demo'})
        result=value.build()
print(json.dumps({'task':task,'demo_only':True,'observation':result},ensure_ascii=False))
'''.replace('task=TASK','task='+repr(task))
    (dest/'smoke.py').write_text(smoke)
    readme = f'''# {task} {PROFILE} public workspace

Python 3.10+, POSIX (Linux/macOS); standard library only.
`submission/` is the original buggy starter. Read PROMPT.md and COMPATIBILITY_CONTRACT.md.
The scenario is materialized in scenario.json; it is public, not a hidden set.

Run from this directory:

    python3 smoke.py

This only starts the supplied implementation and prints its observable result. It contains no
host oracle, expected benchmark answers, private evaluation driver or automatic score.
Write and run your own tests, then freeze your submission and hand it to the organizer.
The organizer evaluates from its independent host checkout:

    python3 /path/to/private-host/code/extreme.py --task {task} --scale {scale} --seed {seed} --submission /path/to/your/submission --output result.json

COMPATIBILITY_CONTRACT.md preserves historical interfaces; current scoring is defined in PROMPT.md.
Machine quality is Q=100 only when every required gate passes, otherwise Q=0. The independent
host records agent elapsed time and tokens; this public demo never estimates model thinking time.

For C3/C4, `submission` must contain `engine.py`, `store.py` or `baseline.py` exporting Store / Builder.
The original starter provides store.py (C3) or engine.py (C4). Add your own tests and DIAGNOSIS.md.
`submission/extreme.py` is the deliberately faulty required stage-v2 extension; see STAGE_PROTOCOL.md.
It must be fixed alongside the legacy repository. Legacy-only submissions are capability_gap and ineligible.
The evaluator executes local code. It is not a security sandbox.
Do not edit the judge or use its expected values from submitted code.
'''
    (dest/'README.md').write_text(readme)
    digest = hashlib.sha256(scenario_file.read_bytes()).hexdigest()
    dims=dimensions(task,scale)
    for dim in dims:
        if dim['name'] in payload['counts']:dim['scope']='generated'
    manifest = dict(task_id=task, profile=PROFILE,version=VERSION, scale=scale, seed=seed,
                    dimensions=dims, scenario_bytes=scenario_file.stat().st_size,
                    scenario_sha256=digest, constructed=payload['counts'], executed=False,
                    starter='submission',public_demo='smoke.py',host_evaluator_included=False)
    (dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return dict(exported=str(dest), **manifest)


def evaluate(task, scale, seed, submission, budget_seconds=None):
    started = time.monotonic()
    budget = budget_seconds or (28 if scale == 'smoke' else 600)
    with tempfile.TemporaryDirectory(prefix='extreme-result-') as tmp:
        out = Path(tmp)/'result.json'
        cmd = [sys.executable,'-B',str(HERE/'extreme_worker.py'),'--task',task,'--scale',scale,
               '--seed',str(seed),'--submission',str(Path(submission).resolve()),'--output',str(out)]
        # The whole child process group is owned by this run, including API/workers.
        process = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                   start_new_session=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=budget)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=3)
        finally:
            # Candidate errors must not leak children even if a harness exits early.
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        if out.exists(): result = json.loads(out.read_text())
        else:
            result = dict(task_id=task,profile=PROFILE,version=VERSION,scale=scale,seed=seed,
                          dimensions=dimensions(task,scale),audit_passed=False,
                          candidate_result=dict(status='timeout' if timed_out else 'harness_error',valid=False,
                                                raw_score=0,quality_score=0),
                          verification=dict(executed=False,error=stderr.decode(errors='replace')[-4000:]))
        result['elapsed_seconds'] = round(time.monotonic()-started,4)
        result['budget_seconds'] = budget
        result['candidate_path'] = str(Path(submission).resolve())
        result['process_exit_code'] = process.returncode
        if timed_out: result['timed_out'] = True
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',choices=['C1','C2','C3','C4'],required=True)
    parser.add_argument('--scale',choices=['smoke','full'],default='smoke')
    parser.add_argument('--seed',type=int,default=260926)
    parser.add_argument('--submission',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--export',type=Path)
    parser.add_argument('--budget-seconds',type=float)
    args=parser.parse_args()
    if args.budget_seconds is not None and args.budget_seconds <= 0: parser.error('budget must be positive')
    if args.export: result=export(args.task,args.scale,args.seed,args.export)
    else:
        result=evaluate(args.task,args.scale,args.seed,args.submission or default_submission(args.task),args.budget_seconds)
        if args.submission is None: result['baseline_result']=dict(result['candidate_result'])
    rendered=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output: args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(rendered)
    print(rendered,end='')
    # CI validates the judge and witnesses, never demands the weak baseline solve the task.
    return 0 if args.export or result.get('audit_passed') else 2


if __name__=='__main__': raise SystemExit(main())
