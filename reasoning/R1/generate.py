#!/usr/bin/env python3
"""Original synthetic benchmark; this generator does not represent field measurements."""
import argparse, json, random


def generate(instance_seed=1601, scenario_seed=9001, n_scenarios=24):
    r = random.Random(instance_seed)
    tasks=[]
    for p in range(8):
        for stage in range(6):
            tid=f'P{p+1}T{stage+1}'
            need=[0,0,0]; need[p%3]=r.randint(1,2); need[(p+stage+1)%3]+=1
            duration=r.randint(4,8)
            deps=[] if stage==0 else [f'P{p+1}T{stage}']
            if stage==4 and p>0: deps.append(f'P{p}T2')
            base_cost=r.randint(8,15)
            tasks.append(dict(id=tid, region=f'G{p//2+1}', zone=f'Z{p%3+1}',
                value=r.randint(25,55)+stage*9, release=stage*2, deadline=22+stage*7+r.randint(0,5),
                mandatory=stage==0, dependencies=deps,
                modes=[dict(id='careful',cost=base_cost+4,duration=duration+2,resources=need,quality=0.995),
                       dict(id='standard',cost=base_cost,duration=duration,resources=need,quality=0.96),
                       dict(id='sprint',cost=base_cost+7,duration=max(2,duration-2),resources=[v+int(v>0) for v in need],quality=0.88)]))
    sr=random.Random(scenario_seed); scenarios=[]
    for n in range(n_scenarios):
        storm=sr.random()<0.29
        caps=[[5,5,5] for _ in range(72)]
        for _ in range(3 if storm else 1):
            skill=sr.randrange(3); start=sr.randrange(6,55); length=sr.randrange(5,14)
            for t in range(start,min(72,start+length)):caps[t][skill]=max(1,caps[t][skill]-sr.randint(1,3))
        factors={t['id']:sr.choice([1.0,1.0,1.15,1.3] if not storm else [1.15,1.35,1.6]) for t in tasks}
        # Common shocks induce correlation; outcomes are deterministic conditional on a scenario.
        q={t['id']:max(0.45,1.0-(0.07 if storm else 0)-sr.choice([0,0,0,0.12,0.23])) for t in tasks}
        scenarios.append(dict(id=f'S{n+1:03}',weight=1,capacity=caps,duration_factor=factors,quality_factor=q))
    return dict(format_version=1,synthetic=True,instance_seed=instance_seed,scenario_seed=scenario_seed,
                horizon=72,budget=450,regions=['G1','G2','G3','G4'],tasks=tasks,scenarios=scenarios)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--instance-seed',type=int,default=1601);p.add_argument('--scenario-seed',type=int,default=9001);p.add_argument('--scenarios',type=int,default=24);p.add_argument('--output',default='input.json');a=p.parse_args()
    if not 1<=a.scenarios<=10000:p.error('scenarios must be 1..10000')
    with open(a.output,'w') as f:json.dump(generate(a.instance_seed,a.scenario_seed,a.scenarios),f,indent=2)
