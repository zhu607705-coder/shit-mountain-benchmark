#!/usr/bin/env python3
import argparse,json,math


def no_duplicates(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise ValueError('duplicate JSON key: '+k)
        d[k]=v
    return d

def load_json(path):
    with open(path) as f:return json.load(f,object_pairs_hook=no_duplicates,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('non-finite JSON number: '+x)))

def validate(data,sub):
    if not isinstance(sub,dict) or set(sub)!={'format_version','tree'} or type(sub['format_version']) is not int or sub['format_version']!=1:raise ValueError('expected format_version=1 and tree only')
    tests={t['id']:t for t in data['tests']};actions={a['id'] for a in data['actions']};c=data['constraints'];count=0;max_depth=0;max_cost=0
    def walk(node,seen,groups,depth,cost):
        nonlocal count,max_depth,max_cost
        count+=1;max_depth=max(max_depth,depth);max_cost=max(max_cost,cost)
        if count>c['max_nodes'] or depth>c['max_depth'] or cost>c['max_path_cost']:raise ValueError('node, depth or path cost limit exceeded')
        if not isinstance(node,dict):raise ValueError('tree node must be object')
        if set(node)=={'action'}:
            if not isinstance(node['action'],str) or node['action'] not in actions:raise ValueError('unknown action')
            return
        if set(node)!={'test','branches'} or not isinstance(node['test'],str) or node['test'] not in tests:raise ValueError('invalid test node schema')
        tid=node['test'];t=tests[tid]
        if tid in seen:raise ValueError('test repeated on a path')
        if any(p not in seen for p in t['prerequisites']):raise ValueError('test prerequisite missing')
        if t['exclusive_group'] and t['exclusive_group'] in groups:raise ValueError('mutually exclusive tests on a path')
        if not isinstance(node['branches'],dict) or set(node['branches'])!=set(t['outcomes']):raise ValueError('all and only declared outcomes must have branches')
        for branch in node['branches'].values():walk(branch,seen|{tid},groups|({t['exclusive_group']} if t['exclusive_group'] else set()),depth+1,cost+t['cost'])
    walk(sub['tree'],set(),set(),0,0)
    return tests,dict(node_count=count,max_depth=max_depth,max_path_cost=max_cost)

def upper_tail(rows,mass):
    remain=mass*sum(w for _,w in rows);denom=remain;total=0.0
    for val,w in sorted(rows,reverse=True):
        take=min(remain,w);total+=take*val;remain-=take
        if remain<=1e-12:break
    return total/denom

def evaluate(data,sub,details=True):
    tests,structure=validate(data,sub);rows=[]
    for world in data['worlds']:
        node=sub['tree'];path=[];cost=0;delay=0;harm=0
        while 'test' in node:
            tid=node['test'];test=tests[tid];outcome=world['outcomes'][tid];path.append(dict(test=tid,outcome=outcome));cost+=test['cost'];delay+=test['delay'];harm+=world['test_harm'][tid];node=node['branches'][outcome]
        action=node['action'];loss=world['action_losses'][action]+harm+delay*world['delay_loss_per_unit']
        row=dict(world=world['id'],weight=world['weight'],action=action,loss=loss,action_loss=world['action_losses'][action],test_harm=harm,delay_loss=delay*world['delay_loss_per_unit'],test_cost=cost,test_count=len(path))
        if details:row['path']=path
        rows.append(row)
    total=sum(w['weight'] for w in rows);o=data['objective']
    def mean(key):return sum(w['weight']*w[key] for w in rows)/total
    ml=mean('loss');tail=upper_tail([(w['loss'],w['weight']) for w in rows],o['tail_mass']);mc=mean('test_cost');objective=ml+o['tail_coefficient']*tail+o['cost_coefficient']*mc
    score=1000/(1+objective/o['score_scale'])
    result=dict(valid=True,feasible=True,raw_score=round(score,9),metrics=dict(objective=objective,mean_loss=ml,cvar_worst_10pct_loss=tail,mean_action_loss=mean('action_loss'),mean_test_harm=mean('test_harm'),mean_delay_loss=mean('delay_loss'),mean_test_cost=mc,mean_test_count=mean('test_count'),**structure),score_formula='1000 / (1 + (mean_loss + 0.45*CVaR_worst_10pct_loss + 0.30*mean_test_cost)/35)')
    if details:result['worlds']=rows
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--submission',required=True);a=p.parse_args()
    try:result=evaluate(load_json(a.input),load_json(a.submission))
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,IndexError,OSError) as e:result=dict(valid=False,feasible=False,raw_score=0,error=str(e))
    print(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2))
if __name__=='__main__':main()
