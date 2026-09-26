#!/usr/bin/env python3
"""Run only the reviewed reasoning baselines and explicit controls; no other tasks."""
import argparse,hashlib,importlib.util,json
from pathlib import Path
BASE=Path(__file__).resolve().parents[2]


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class PriorRepair:
    def act(self,m,h,b):
        risks=[sum(p*loss for p,loss in zip(m['prior'],row)) for row in m['terminal_losses']]
        return {'repair':m['actions'][min(range(len(risks)),key=risks.__getitem__)]}

class FIFO:
    def act(self,o):
        done=set(o['done']);waiting=sorted([j for j in o['jobs'] if j['state']=='waiting' and all(d in done for d in j['deps'])],key=lambda j:(j['release'],j['id']))
        used=set();power=o['free_power'];actions=[]
        for machine in sorted(o['machines'],key=lambda m:m['id']):
            if not machine['available']:continue
            for job in waiting:
                if job['id'] not in used and machine['id'] in job['eligible'] and job['power']<=power:
                    actions.append({'job':job['id'],'machine':machine['id']});used.add(job['id']);power-=job['power'];break
        return actions


def main():
    p=argparse.ArgumentParser();p.add_argument('--task',choices=['R3','R4','both'],default='both');p.add_argument('--original',action='store_true');a=p.parse_args()
    for tid,oldid,control in [('R3','R1',PriorRepair()),('R4','R2',FIFO())]:
        if a.task not in [tid,'both']:continue
        task_dir=BASE/'reasoning'/tid
        ep=BASE/'imports/pro_v01/upstream/organizer/organizer'/(oldid.lower()+'.py') if a.original else task_dir/'evaluator.py'
        evaluator=load(ep,'review_eval_'+tid);policy=load(task_dir/'baseline.py','review_policy_'+tid)
        baseline=evaluator.evaluate(policy);reference=evaluator.evaluate(control)
        result={'task':tid,'adapted':not a.original,'evaluation_kind':'public reproducibility run','baseline':baseline,'control':reference}
        output=task_dir/('review_original_metrics.json' if a.original else 'review_adapted_metrics.json');output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        print(tid, 'baseline loss',baseline['objective_loss'],'control loss',reference['objective_loss'])
if __name__=='__main__':main()
