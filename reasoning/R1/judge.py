#!/usr/bin/env python3
import argparse, json, math, sys


def no_duplicates(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise ValueError('duplicate JSON key: '+k)
        d[k]=v
    return d

def load_json(path):
    with open(path) as f:return json.load(f,object_pairs_hook=no_duplicates,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('non-finite JSON number: '+x)))

def validate(data, sub):
    if not isinstance(sub,dict) or set(sub)!={'format_version','plan'} or type(sub['format_version']) is not int or sub['format_version']!=1:raise ValueError('expected format_version=1 and plan only')
    if not isinstance(sub['plan'],list) or len(sub['plan'])>len(data['tasks']):raise ValueError('plan must be a bounded list')
    tasks={t['id']:t for t in data['tasks']};seen=set();cost=0
    for x in sub['plan']:
        if not isinstance(x,dict) or set(x)!={'task','mode'} or not isinstance(x['task'],str) or not isinstance(x['mode'],str):raise ValueError('each plan entry has string task and mode only')
        if x['task'] not in tasks or x['task'] in seen:raise ValueError('unknown or duplicate task')
        t=tasks[x['task']]
        if any(dep not in seen for dep in t['dependencies']):raise ValueError('every dependency must appear earlier in plan')
        modes={m['id']:m for m in t['modes']}
        if x['mode'] not in modes:raise ValueError('unknown mode')
        cost+=modes[x['mode']]['cost'];seen.add(x['task'])
    if any(t['mandatory'] and t['id'] not in seen for t in data['tasks']):raise ValueError('mandatory task omitted')
    if cost>data['budget']:raise ValueError('budget exceeded')
    return tasks,cost

def lower_tail(rows, mass=0.20):
    remaining=mass*sum(w for _,w in rows);denom=remaining;total=0
    for val,w in sorted(rows):
        take=min(remaining,w);total+=take*val;remaining-=take
        if remaining<=1e-12:break
    return total/denom

def evaluate(data,sub,details=True):
    tasks,cost=validate(data,sub);h=data['horizon'];targets={g:sum(t['value'] for t in tasks.values() if t['region']==g) for g in data['regions']}
    total_value=sum(targets.values());rows=[]
    for sc in data['scenarios']:
        used=[[0,0,0] for _ in range(h)];zones={t['zone']:[False]*h for t in tasks.values()};ends={};quality={};delivery={g:0.0 for g in targets};schedule=[];late=0
        for x in sub['plan']:
            t=tasks[x['task']];mode=next(m for m in t['modes'] if m['id']==x['mode']);dur=math.ceil(mode['duration']*sc['duration_factor'][t['id']]);start=None
            if all(d in ends for d in t['dependencies']):
                earliest=max([t['release']]+[ends[d] for d in t['dependencies']])
                for s in range(earliest,h-dur+1):
                    if all(not zones[t['zone']][k] and all(used[k][j]+mode['resources'][j]<=sc['capacity'][k][j] for j in range(3)) for k in range(s,s+dur)):
                        start=s;break
            if start is None:
                if details:schedule.append(dict(task=t['id'],status='unscheduled',earned_value=0))
                continue
            end=start+dur;ends[t['id']]=end;quality[t['id']]=mode['quality']*sc['quality_factor'][t['id']]*min([quality[d] for d in t['dependencies']] or [1.0])
            earned=t['value']*quality[t['id']]*max(0,1-max(0,end-t['deadline'])/18)
            delivery[t['region']]+=earned;late+=int(end>t['deadline'])
            for k in range(start,end):
                zones[t['zone']][k]=True
                for j in range(3):used[k][j]+=mode['resources'][j]
            if details:schedule.append(dict(task=t['id'],start=start,end=end,quality=round(quality[t['id']],6),earned_value=round(earned,6)))
        row=dict(scenario=sc['id'],weight=sc['weight'],coverage=sum(delivery.values())/total_value,
                 min_region_coverage=min(delivery[g]/targets[g] for g in targets),region_coverage={g:delivery[g]/targets[g] for g in targets},
                 completed=len(ends),unscheduled=len(sub['plan'])-len(ends),late=late)
        if details:row['schedule']=schedule
        rows.append(row)
    w=sum(r['weight'] for r in rows);mean=sum(r['weight']*r['coverage'] for r in rows)/w;fair=sum(r['weight']*r['min_region_coverage'] for r in rows)/w
    tail=lower_tail([(r['coverage'],r['weight']) for r in rows]);spend=cost/data['budget'];score=max(0,1000*(0.55*mean+0.25*tail+0.20*fair)-50*spend)
    result=dict(valid=True,feasible=True,raw_score=round(score,9),metrics=dict(mean_coverage=mean,worst_20pct_coverage=tail,mean_min_region_coverage=fair,cost=cost,budget=data['budget'],selected_tasks=len(sub['plan']),total_tasks=len(tasks),available_total_value=total_value),score_formula='max(0, 1000*(0.55*mean_coverage + 0.25*worst_20pct_coverage + 0.20*mean_min_region_coverage) - 50*cost/budget)')
    if details:result['scenarios']=rows
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--submission',required=True);a=p.parse_args()
    try:result=evaluate(load_json(a.input),load_json(a.submission))
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,IndexError,OSError) as e:result=dict(valid=False,feasible=False,raw_score=0,error=str(e))
    print(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2))
if __name__=='__main__':main()
