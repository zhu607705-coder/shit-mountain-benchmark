#!/usr/bin/env python3
"""Synthetic industrial faults, sensors and interventions. No medical or real measurement data."""
import argparse,json,random


def generate(design_seed=2201,world_seed=9101,n_worlds=180):
    r=random.Random(design_seed)
    tests=[]
    for i in range(18):
        costs=[1,1,1,2,2,2,3,3,4,4,5,5,6,6,6,7,7,8]
        signatures=[(s//(2**(i%3)))%2 for s in range(8)] if i<9 else [r.randrange(3) for _ in range(8)]
        tests.append(dict(id=f'T{i:02}',outcomes=['0','1','2'],cost=costs[i],delay=1+i//6,
                    prerequisites=[] if i<9 else ([f'T{i%3:02}'] if i<15 else [f'T{3+i%3:02}']),
                    exclusive_group='destructive_sample' if 12<=i<=14 else None,
                    channel=i%3,nominal_signatures=signatures,noise_probability=0.24 if i<9 else 0.10))
    actions=[dict(id=f'A{i:02}',description=f'针对合成故障类别 {i} 的局部修复') for i in range(8)]
    actions.extend([dict(id='A08',description='对类别 0–3 的广域修复'),dict(id='A09',description='对类别 4–7 的广域修复'),dict(id='A10',description='停机隔离并交专业团队，损失高但稳定')])
    wr=random.Random(world_seed);worlds=[]
    for n in range(n_worlds):
        state=wr.choices(range(8),weights=[20,17,15,13,12,10,8,5])[0];severity=wr.choice([0.8,1.0,1.0,1.4,2.0]);rare=wr.random()<0.065
        channel_faults=[wr.random()<0.18 for _ in range(3)];outcomes={};harm={}
        for t in tests:
            value=t['nominal_signatures'][state]
            if channel_faults[t['channel']] and int(t['id'][1:])<9:value=1-value
            if wr.random()<t['noise_probability']:value=wr.randrange(3)
            outcomes[t['id']]=str(value)
            harm[t['id']]=round((0.15*t['cost']*severity)+(9.0 if rare and t['exclusive_group'] else 0),3)
        losses={}
        for i in range(8):
            losses[f'A{i:02}']=round((3 if i==state else 28+7*abs(i-state))*severity+(240 if rare and i!=state else 0),3)
        losses['A08']=round((15 if state<4 else 57)*severity+(90 if rare and state>=4 else 0),3)
        losses['A09']=round((15 if state>=4 else 57)*severity+(90 if rare and state<4 else 0),3)
        losses['A10']=round(44+5*severity,3)
        worlds.append(dict(id=f'W{n+1:04}',weight=1,latent_class=state,rare_event=rare,outcomes=outcomes,test_harm=harm,
                           delay_loss_per_unit=round(0.45*severity+(1.5 if rare else 0),3),action_losses=losses))
    return dict(format_version=1,synthetic=True,design_seed=design_seed,world_seed=world_seed,
                constraints=dict(max_depth=7,max_nodes=364,max_path_cost=24),tests=tests,actions=actions,worlds=worlds,
                objective=dict(tail_mass=0.10,tail_coefficient=0.45,cost_coefficient=0.30,score_scale=35))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--design-seed',type=int,default=2201);p.add_argument('--world-seed',type=int,default=9101);p.add_argument('--worlds',type=int,default=180);p.add_argument('--output',default='input.json');a=p.parse_args()
    if not 1<=a.worlds<=100000:p.error('worlds must be 1..100000')
    with open(a.output,'w') as f:json.dump(generate(a.design_seed,a.world_seed,a.worlds),f,ensure_ascii=False,indent=2)
