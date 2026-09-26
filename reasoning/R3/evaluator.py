from __future__ import annotations
import itertools,random,math,json,hashlib,importlib.util,copy
from pathlib import Path


def make_model(seed=41, n=10):
    r=random.Random(seed)
    names=[f'service-{i:02d}' for i in range(n)]
    hypotheses=[[]]+[[i] for i in range(n)]+[list(p) for p in itertools.combinations(range(n),2)]
    prior=[0.08]+[0.42/n]*n+[0.50/(n*(n-1)//2)]*(n*(n-1)//2)
    weights=[r.randint(18,48) for _ in range(n)]
    actions=hypotheses[:]
    tests=[]
    groups=[[i] for i in range(n)]+[r.sample(range(n),r.randint(2,4)) for _ in range(n)]
    for group in groups:
        sensitivity=r.uniform(.65,.93); fp=r.uniform(.04,.24)
        probs=[min(.97,fp+(1-fp)*(1-(1-sensitivity)**len(set(group)&set(h)))) for h in hypotheses]
        tests.append({'name':'probe-'+str(len(tests)), 'group':group,
                      'cost':round(r.uniform(.7,2.2),2),'probability':probs})
    losses=[]
    for a in actions:
        losses.append([sum(weights[i] for i in h if i not in a)+4*len(set(a)-set(h))+1.5*len(a)
                       for h in hypotheses])
    return {'components':names,'hypotheses':hypotheses,'prior':prior,'tests':tests,
            'actions':actions,'terminal_losses':losses,'budget':9.0,'max_queries':8}


def run_case(model, policy, seed):
    # Policy observations are values, never writable aliases of simulator state.
    model=copy.deepcopy(model)
    r=random.Random(seed)
    h=r.choices(range(len(model['hypotheses'])),weights=model['prior'])[0]
    history=[]; spent=0.; query_counts={}; invalid=None
    for turn in range(model['max_queries']+1):
        try:
            action=policy.act(copy.deepcopy(model),copy.deepcopy(history),model['budget']-spent)
        except Exception as exc:
            invalid='policy exception: '+type(exc).__name__+': '+str(exc)[:200];break
        if type(action) is not dict or set(action) not in ({'repair'},{'test'}):
            invalid='action must contain exactly repair or test';break
        if 'repair' in action:
            repair=action['repair']
            if type(repair) is not list or any(type(i) is not int for i in repair):
                invalid='repair must be a list of integer component indices';break
            a=sorted(repair)
            if len(a)!=len(set(a)) or a not in model['actions']: invalid='invalid repair';break
            j=model['actions'].index(a)
            return {'loss':round(spent+model['terminal_losses'][j][h],6),'cost':spent,
                    'queries':len(history),'exact':a==model['hypotheses'][h], 'valid':True,
                    'history':history,'repair':a,'truth':model['hypotheses'][h]}
        j=action['test']
        if type(j) is not int or j<0 or j>=len(model['tests']) or turn>=model['max_queries']:
            invalid='invalid/excess query';break
        test=model['tests'][j]
        if spent+test['cost']>model['budget']+1e-9: invalid='over budget';break
        # Common random numbers keyed by episode/test/repetition, not policy path.
        k=query_counts.get(j,0); query_counts[j]=k+1
        key=f'{seed}:{j}:{k}'.encode(); u=int.from_bytes(hashlib.sha256(key).digest()[:8],'big')/2**64
        positive=u<test['probability'][h]
        spent+=test['cost'];history.append({'test':j,'positive':positive})
    return {'loss':200.,'valid':False,'error':invalid,'queries':len(history),'exact':False,'history':history}


def _upper_tail(values,mass=.1):
    remaining=len(values)*mass;denominator=remaining;total=0.
    for value in sorted(values,reverse=True):
        take=min(1.,remaining);total+=take*value;remaining-=take
        if remaining<=1e-12:break
    return total/denominator


def evaluate(policy,models=3,episodes=30,*,model_seed=41,episode_seed=90000):
    if type(models) is not int or models<1 or type(episodes) is not int or not 1<=episodes<=10000:
        raise ValueError('positive model count and 1..10000 episodes per model required')
    if type(model_seed) is not int or type(episode_seed) is not int:raise ValueError('integer seeds required')
    rows=[]
    for m in range(models):
        model=make_model(model_seed+m)
        for k in range(episodes):rows.append(run_case(model,policy,episode_seed+m*10000+k))
    losses=[x['loss'] for x in rows];mean=sum(losses)/len(losses);cvar=_upper_tail(losses)
    valid_count=sum(x['valid'] for x in rows)
    return {'episodes':len(rows),'valid':valid_count==len(rows),'valid_episodes':valid_count,
            'sampling':{'model_seed':model_seed,'episode_seed':episode_seed,'models':models,'episodes_per_model':episodes,'public_default_seeds':model_seed==41 and episode_seed==90000},
            'exact_diagnosis_rate':sum(x['exact'] for x in rows)/len(rows),
            'mean_queries':sum(x['queries'] for x in rows)/len(rows),
            'mean_loss':mean,'worst_decile_mean_loss':cvar,
            'objective_loss':.8*mean+.2*cvar,'episodes_detail':rows}
