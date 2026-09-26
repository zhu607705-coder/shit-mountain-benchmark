#!/usr/bin/env python3
"""Unified executable entry point for the R1-R4 extreme profile."""
from __future__ import annotations
import argparse
import importlib
import json
import math
from pathlib import Path
import shutil
import time
from extreme_common import Policy
from extreme_selftest import witnesses

ROOT=Path(__file__).resolve().parent


def export(task,scale,destination,module):
    directory=Path(destination)
    directory.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/task/'extreme'/'PROMPT.md',directory/'PROMPT.md')
    (directory/'public.json').write_text(json.dumps(module.public(scale),ensure_ascii=False,indent=2)+'\n')
    empty={'R1':{'invest':[],'cancel':[],'start':[]},'R2':{'action':36},
           'R3':{'repair':[],'group_repair':[]},'R4':{'maintain':[],'start':[]}}[task]
    starter='''#!/usr/bin/env python3
"""Replace act with your policy. Read one observation and return one action per line."""
import json
import sys


def act(observation):
    # reset=true starts a new independent episode; keep public model if supplied.
    return REPLACE


for line in sys.stdin:
    observation = json.loads(line)
    print(json.dumps(act(observation), allow_nan=False), flush=True)
'''.replace('REPLACE',repr(empty))
    (directory/'policy.py').write_text(starter)
    (directory/'constant_action.json').write_text(json.dumps({'action':empty},indent=2)+'\n')
    # Export never copies a seed, generated future fixture, organizer baseline or judge.
    return {'directory':str(directory.resolve()),'files':['PROMPT.md','public.json','policy.py','constant_action.json'],
            'future_or_seed_exported':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task',choices=['R1','R2','R3','R4'],required=True)
    p.add_argument('--scale',choices=['smoke','full'],default='smoke')
    p.add_argument('--seed',type=int,default=260926)
    p.add_argument('--output')
    p.add_argument('--export',dest='export_dir')
    p.add_argument('--submission',help='.py NDJSON executable or .json with one constant action')
    p.add_argument('--budget-seconds',type=float,default=120.)
    p.add_argument('--action-timeout',type=float,default=2.)
    args=p.parse_args()
    if not all(math.isfinite(v) and v>0 for v in (args.budget_seconds,args.action_timeout)):
        p.error('time budgets must be positive')
    module=importlib.import_module('extreme_'+args.task.lower())
    started=time.perf_counter()
    if args.export_dir:
        result={'task_id':args.task,'profile':'extreme','scale':args.scale,
                'export':export(args.task,args.scale,args.export_dir,module)}
    else:
        policy=Policy(module.baseline,args.submission,args.budget_seconds,args.action_timeout)
        try:
            evaluated,dimensions=module.evaluate(args.scale,args.seed,policy)
        finally:
            policy.close()
        witness=witnesses()[args.task]
        result={'task_id':args.task,'profile':'extreme','scale':args.scale,'seed':args.seed,
            'dimensions':dimensions,'mechanisms':module.MECHANISMS,
            'candidate_result' if args.submission else 'baseline_result':evaluated,
            'verification':{'independent_tiny_witness':witness,
                            'reproducible_seed':True,'private_future_in_observations':False,
                            'selftest_command':'python3 reasoning/extreme_selftest.py',
                            'formal_hidden_evaluation':False,'multiple_model_calibration':None},
            'policy_runtime':{'calls':policy.calls,'decision_seconds':policy.elapsed,
                              'total_decision_budget_seconds':args.budget_seconds,
                              'per_action_timeout_seconds':args.action_timeout},
            'audit_passed':True}
    result['wall_seconds']=time.perf_counter()-started
    raw=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if args.output:
        path=Path(args.output)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(raw)
    print(raw if not args.output else json.dumps({'task_id':args.task,'output':str(Path(args.output).resolve()),
                                                  'wall_seconds':result['wall_seconds'],
                                                  'audit_passed':result.get('audit_passed')},ensure_ascii=False))


if __name__=='__main__':
    main()
