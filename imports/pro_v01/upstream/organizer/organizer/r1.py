from __future__ import annotations
import itertools,random,math,json,hashlib,importlib.util
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
    r=random.Random(seed)
    h=r.choices(range(len(model['hypotheses'])),weights=model['prior'])[0]
    history=[]; spent=0.; query_counts={}; invalid=None
    for turn in range(model['max_queries']+1):
        action=policy.act(model,history,model['budget']-spent)
        if 'repair' in action:
            a=sorted(action['repair'])
            if a not in model['actions']: invalid='invalid repair';break
            j=model['actions'].index(a)
            return {'loss':round(spent+model['terminal_losses'][j][h],6),'cost':spent,
                    'queries':len(history),'exact':a==model['hypotheses'][h], 'valid':True,
                    'history':history,'repair':a,'truth':model['hypotheses'][h]}
        j=action.get('test',-1)
        if not isinstance(j,int) or j<0 or j>=len(model['tests']) or turn>=model['max_queries']:
            invalid='invalid/excess query';break
        test=model['tests'][j]
        if spent+test['cost']>model['budget']+1e-9: invalid='over budget';break
        # Common random numbers keyed by episode/test/repetition, not policy path.
        k=query_counts.get(j,0); query_counts[j]=k+1
        key=f'{seed}:{j}:{k}'.encode(); u=int.from_bytes(hashlib.sha256(key).digest()[:8],'big')/2**64
        positive=u<test['probability'][h]
        spent+=test['cost'];history.append({'test':j,'positive':positive})
    return {'loss':200.,'valid':False,'error':invalid,'queries':len(history),'exact':False}


def evaluate(policy,models=3,episodes=30):
    rows=[]
    for m in range(models):
        model=make_model(41+m)
        for k in range(episodes):rows.append(run_case(model,policy,90000+m*10000+k))
    ls=sorted(x['loss'] for x in rows)
    tail=ls[-max(1,math.ceil(.1*len(ls))):]
    mean=sum(ls)/len(ls); cvar=sum(tail)/len(tail)
    return {'episodes':len(rows),'valid_episodes':sum(x['valid'] for x in rows),
            'exact_diagnosis_rate':sum(x['exact'] for x in rows)/len(rows),
            'mean_queries':sum(x['queries'] for x in rows)/len(rows),
            'mean_loss':mean,'worst_decile_mean_loss':cvar,
            'objective_loss':.8*mean+.2*cvar,'episodes_detail':rows}
