#!/usr/bin/env python3
"""Cost-aware greedy tree induction; conditional CVaR is only a heuristic for global CVaR."""
import argparse,json
from judge import load_json,evaluate,upper_tail


def build(data,risk,depth_limit,min_leaf):
    tests={t['id']:t for t in data['tests']};actions=[a['id'] for a in data['actions']];worlds=data['worlds'];constraints=data['constraints'];cc=data['objective']['cost_coefficient']
    def leaf(rows,cost):
        if not rows:return 'A10',0
        total=sum(worlds[i]['weight'] for i,_ in rows);best=None;value=float('inf')
        for action in actions:
            losses=[(base+worlds[i]['action_losses'][action],worlds[i]['weight']) for i,base in rows]
            obj=sum(l*w for l,w in losses)/total+risk*upper_tail(losses,0.10)+cc*cost
            if obj<value:best,value=action,obj
        return best,value
    def recurse(rows,seen,groups,depth,cost):
        action,terminal=leaf(rows,cost)
        if depth>=depth_limit or len(rows)<min_leaf:return {'action':action}
        total=sum(worlds[i]['weight'] for i,_ in rows);best=None;best_value=terminal
        for tid,t in tests.items():
            if tid in seen or any(p not in seen for p in t['prerequisites']) or (t['exclusive_group'] and t['exclusive_group'] in groups) or cost+t['cost']>constraints['max_path_cost']:continue
            groups_rows={o:[] for o in t['outcomes']}
            for i,base in rows:
                w=worlds[i];groups_rows[w['outcomes'][tid]].append((i,base+w['test_harm'][tid]+t['delay']*w['delay_loss_per_unit']))
            obj=0.0
            for child in groups_rows.values():
                if child:obj+=sum(worlds[i]['weight'] for i,_ in child)/total*leaf(child,cost+t['cost'])[1]
            if obj<best_value-1e-9:best,best_value=(tid,groups_rows),obj
        if best is None:return {'action':action}
        tid,partitions=best;t=tests[tid]
        return {'test':tid,'branches':{o:recurse(child,seen|{tid},groups|({t['exclusive_group']} if t['exclusive_group'] else set()),depth+1,cost+t['cost']) for o,child in partitions.items()}}
    return dict(format_version=1,tree=recurse([(i,0.0) for i in range(len(worlds))],set(),set(),0,0))


def solve(data):
    best=None;score=-1
    for risk in [0,0.2,0.45,0.8,1.2]:
        for depth in [3,4,5]:
            sub=build(data,risk,min(depth,data['constraints']['max_depth']),3)
            result=evaluate(data,sub,details=False)
            if result['raw_score']>score:best,score=sub,result['raw_score']
    return best
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    with open(a.output,'w') as f:json.dump(solve(load_json(a.input)),f,indent=2)
