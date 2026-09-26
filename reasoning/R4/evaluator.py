from __future__ import annotations
import random,math,hashlib,copy


def generate(seed,n=60,m=6,horizon=300):
    r=random.Random(seed);jobs=[]
    for i in range(n):
        release=r.randrange(0,150)
        possible=[j['id'] for j in jobs if j['release']<=release]
        deps=r.sample(possible,min(len(possible),r.choices([0,1,2],[.60,.30,.10])[0]))
        jobs.append({'id':f'J{i:03d}','release':release,'deadline':release+r.randint(18,90),
                     'duration':r.randint(6,28),'weight':r.randint(1,9),'power':r.randint(1,4),
                     'eligible':r.sample(range(m),r.randint(1,m)), 'deps':deps,'family':r.randrange(3),'state':'waiting'})
    machines=[{'id':i,'speed':r.uniform(.75,1.35),'family':None} for i in range(m)]
    outages={i:[(r.randint(35,110),r.randint(4,12)),(r.randint(160,230),r.randint(4,12))] for i in range(m)}
    return jobs,machines,outages,horizon


def run_case(policy,seed):
    jobs,ms,outages,H=generate(seed);index={j['id']:j for j in jobs};run={};done={};energy=0;starts=0;invalid=[]
    for t in range(H+1):
        for mid in list(run):
            x=run[mid]
            if x['end']<=t:
                done[x['job']]=t;index[x['job']]['state']='done';del run[mid]
        down={mid for mid,slots in outages.items() if any(a<=t<a+d for a,d in slots)}
        for mid in list(run):
            if mid in down:
                index[run[mid]['job']]['state']='waiting';del run[mid]
        if t==H:break
        visible=[dict(j) for j in jobs if j['release']<=t]
        used_power=sum(index[x['job']]['power'] for x in run.values())
        obs={'time':t,'jobs':visible,'done':list(done),'horizon':H,'free_power':10-used_power,
             'machines':[dict(m,available=(m['id'] not in run and m['id'] not in down)) for m in ms]}
        try:
            acts=policy.act(copy.deepcopy(obs))
        except Exception as exc:
            invalid.append('policy exception: '+type(exc).__name__+': '+str(exc)[:200]);break
        if type(acts) is not list:
            invalid.append('actions must be a list');break
        if len(acts)>len(ms):
            invalid.append('more actions than machines');break
        for a in acts:
            if type(a) is not dict or set(a)!={'job','machine'}:
                invalid.append('action must contain exactly job and machine');continue
            jid=a['job'];mid=a['machine']
            if type(jid) is not str or type(mid) is not int:
                invalid.append('job must be string and machine must be integer');continue
            j=index.get(jid)
            if not j or not 0<=mid<len(ms):invalid.append('unknown action');continue
            if j['release']>t or j['state']!='waiting' or mid in run or mid in down or mid not in j['eligible'] or not all(d in done for d in j['deps']) or used_power+j['power']>10:
                invalid.append('infeasible action');continue
            # Exogenous duration realization shared across policies for job/machine.
            u=int.from_bytes(hashlib.sha256(f'{seed}:{jid}:{mid}'.encode()).digest()[:8],'big')/2**64
            duration=math.ceil(j['duration']*ms[mid]['speed']*(.75+.5*u))+(0 if ms[mid]['family']==j['family'] else 3)
            ms[mid]['family']=j['family'];run[mid]={'job':jid,'end':t+duration};j['state']='running';starts+=1;used_power+=j['power']
        energy+=sum(index[x['job']]['power'] for x in run.values())
    # Missing jobs cannot make an apparently fast schedule cheap.
    late=sum(j['weight']*max(0,done.get(j['id'],H+180)-j['deadline']) for j in jobs)
    unfinished=sum(j['weight'] for j in jobs if j['id'] not in done)
    denom=sum(j['weight'] for j in jobs)
    loss=late/denom+40*unfinished/denom+.002*energy+.25*max(0,starts-len(jobs))
    return {'objective_loss':loss,'completed':len(done),'jobs':len(jobs),'weighted_tardiness':late,
            'energy':energy,'starts':starts,'invalid_actions':len(invalid),'valid':not invalid,'errors':invalid}


def _upper_tail(values,mass=.1):
    remaining=len(values)*mass;denominator=remaining;total=0.
    for value in sorted(values,reverse=True):
        take=min(1.,remaining);total+=take*value;remaining-=take
        if remaining<=1e-12:break
    return total/denominator


def evaluate(policy,episodes=20,*,seed_base=72000):
    if type(episodes) is not int or episodes<1 or type(seed_base) is not int:raise ValueError('positive integer episodes and integer seed_base required')
    rows=[run_case(policy,seed_base+i) for i in range(episodes)]
    values=[x['objective_loss'] for x in rows];mean=sum(values)/episodes;tail=_upper_tail(values)
    valid_count=sum(x['valid'] for x in rows)
    return {'episodes':episodes,'valid':valid_count==episodes,'valid_episodes':valid_count,
            'sampling':{'seed_base':seed_base,'episodes':episodes,'public_default_seeds':seed_base==72000},
            'mean_completed':sum(x['completed'] for x in rows)/episodes,
            'mean_loss':mean,'worst_decile_mean_loss':tail,
            'objective_loss':.8*mean+.2*tail,'episodes_detail':rows}
