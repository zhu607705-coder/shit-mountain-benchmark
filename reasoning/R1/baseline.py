#!/usr/bin/env python3
"""Deterministic, deliberately modest heuristic; no optimality claim."""
import argparse,json,random
from judge import evaluate,load_json


def solve(data,trials=96):
    r=random.Random(713);tasks={t['id']:t for t in data['tasks']};best=None;bestscore=-1
    for trial in range(trials):
        remaining=set(tasks);plan=[];seen=set();cost=0;counts={g:0 for g in data['regions']}
        mandatory=[t['id'] for t in data['tasks'] if t['mandatory']]
        mode_map={tid:('standard' if trial<8 or r.random()<0.63 else r.choice(['careful','sprint'])) for tid in tasks}
        def mode(tid):return next(m for m in tasks[tid]['modes'] if m['id']==mode_map[tid])
        # Reserve enough for every mandatory root before adding optional work.
        r.shuffle(mandatory)
        for tid in mandatory:
            plan.append(dict(task=tid,mode=mode_map[tid]));cost+=mode(tid)['cost'];seen.add(tid);remaining.remove(tid);counts[tasks[tid]['region']]+=1
        while remaining:
            eligible=[tid for tid in sorted(remaining) if all(d in seen for d in tasks[tid]['dependencies']) and cost+mode(tid)['cost']<=data['budget']]
            if not eligible:break
            def rank(tid):
                t=tasks[tid];m=mode(tid)
                fairness=1/(1+0.18*counts[t['region']])
                return (t['value']/((m['cost']**0.5)*(m['duration']**0.7)))*fairness*r.uniform(0.5,1.5)
            tid=max(eligible,key=rank);plan.append(dict(task=tid,mode=mode_map[tid]));cost+=mode(tid)['cost'];seen.add(tid);remaining.remove(tid);counts[tasks[tid]['region']]+=1
        sub=dict(format_version=1,plan=plan);score=evaluate(data,sub,details=False)['raw_score']
        if score>bestscore:best,bestscore=sub,score
    return best

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--trials',type=int,default=96);a=p.parse_args()
    if not 1<=a.trials<=100000:p.error('trials must be positive')
    with open(a.output,'w') as f:json.dump(solve(load_json(a.input),a.trials),f,indent=2)
