"""R4: online dispatch with wear, maintenance and consumable production chains."""
from __future__ import annotations
import math
import random
from extreme_common import InvalidAction, exact, integer, distinct, keyed, scored

MECHANISMS = [
    'Wear-dependent failures restart jobs and destroy already-issued consumables; preventive maintenance competes for time and spares.',
    'Low-value precursor jobs manufacture consumables required by valuable jobs, coupling dispatch with inventory control.',
    'Changing power capacity causes brownout interrupts; setup changes and specialized machines create opportunity costs.',
    'Future arrivals, failure draws, shipments and realized durations are hidden; decisions use a finite observation window.']


def generate(seed, scale):
    r = random.Random(seed)
    n, m, H, chains = (720, 24, 600, 24) if scale == 'full' else (60, 6, 120, 6)
    jobs = []
    for i in range(n):
        stage, chain = divmod(i, chains)
        release = stage*(13 if scale == 'full' else 7)
        deps = [f'J{i-chains:04d}'] if stage else []
        reagent = (stage+chain) % 3
        producer = stage % 4 == 0
        eligible = ([chain % 3] if stage % 7 == 6 else
                    sorted(set([chain % m, (chain+3) % m, (chain+7) % m])))
        jobs.append({'id': f'J{i:04d}', 'release': release,
            'deadline': release+r.randint(18, 48), 'duration': r.randint(3,12),
            'weight': r.randint(1,4) if producer else r.randint(5,12),
            'family': chain % 4, 'power': r.randint(1,4), 'eligible': eligible,
            'deps': deps, 'consumes': [int(k == reagent)*(1 if producer else 2) for k in range(3)],
            'produces': [int(k == (reagent+1)%3)*7 if producer else 0 for k in range(3)]})
    return {'jobs': jobs, 'machines': [{'id': i, 'speed': round(r.uniform(.7,1.35),3)} for i in range(m)],
            'horizon': H, 'inventory': [36,36,36] if scale == 'full' else [10,10,10],
            'spares': 20 if scale == 'full' else 5,
            'base_power': 36 if scale == 'full' else 10}


def baseline(obs):
    available = [x for x in obs['machines'] if x['available']]
    ready = [j for j in obs['jobs'] if j['state'] == 'waiting' and all(d in obs['done'] for d in j['deps'])]
    ready.sort(key=lambda j: (j['deadline'], -j['weight'], j['id']))
    inventory, power, spares = obs['inventory'][:], obs['free_power'], obs['spares']
    starts, maintain = [], []
    for machine in sorted(available, key=lambda x: x['speed']):
        if machine['wear'] >= 38 and spares > 0:
            maintain.append(machine['id'])
            spares -= 1
            continue
        for j in ready:
            if machine['id'] not in j['eligible'] or j['power'] > power:
                continue
            if any(inventory[k] < j['consumes'][k] for k in range(3)):
                continue
            starts.append({'job': j['id'], 'machine': machine['id']})
            inventory = [inventory[k]-j['consumes'][k] for k in range(3)]
            power -= j['power']
            ready.remove(j)
            break
    return {'maintain': maintain, 'start': starts}


def run_episode(instance, policy, seed, episode=0):
    jobs = instance['jobs']
    index = {j['id']: j for j in jobs}
    state = {j['id']: 'waiting' for j in jobs}
    machines = [dict(m, wear=0, family=None, down_until=0) for m in instance['machines']]
    running, done = {}, {}
    inventory = instance['inventory'][:]
    spares = instance['spares']
    energy = starts = interruptions = maintenance = 0
    consumed = [0,0,0]
    error = None
    for t in range(instance['horizon']+1):
        for mid in list(running):
            work = running[mid]
            if work['end'] <= t:
                j = index[work['job']]
                state[j['id']] = 'done'
                done[j['id']] = t
                inventory = [inventory[k]+j['produces'][k] for k in range(3)]
                del running[mid]
        if t == instance['horizon']:
            break
        if t and t % 40 == 0:
            for k in range(3):
                inventory[k] += int(keyed(seed, 'supply', t, k)*7)
        power_cap = instance['base_power'] - (5 if keyed(seed,'power',t//10) < .2 else 0)
        power_cap = max(2,power_cap)
        for mid in list(running):
            machine = machines[mid]
            failure_probability = max(0., (machine['wear']-18)/550)
            if keyed(seed, 'failure', t, mid) < failure_probability:
                state[running[mid]['job']] = 'waiting'
                del running[mid]
                machine['down_until'] = t+4
                machine['wear'] = max(0,machine['wear']-8)
                interruptions += 1
        # Brownouts interrupt high-power jobs first, then higher machine id.
        used_power = sum(index[w['job']]['power'] for w in running.values())
        for mid in sorted(running, key=lambda mid:(index[running[mid]['job']]['power'],mid), reverse=True):
            if used_power <= power_cap:
                break
            j = index[running[mid]['job']]
            used_power -= j['power']
            state[j['id']] = 'waiting'
            del running[mid]
            interruptions += 1
        visible = [dict(j, state=state[j['id']]) for j in jobs if j['release'] <= t]
        obs = {'task': 'R4', 'reset': t == 0, 'episode': episode, 'time': t,
               'horizon': instance['horizon'], 'jobs': visible, 'done': done,
               'inventory': inventory, 'spares': spares, 'free_power': power_cap-used_power,
               'power_capacity': power_cap,
               'machines': [{k:v for k,v in machine.items() if k != 'down_until'} |
                   {'available': machine['id'] not in running and machine['down_until'] <= t,
                    'running_job': running.get(machine['id'],{}).get('job')}
                   for machine in machines]}
        try:
            a = policy(obs)
            exact(a, ['maintain','start'])
            if type(a['maintain']) is not list or type(a['start']) is not list:
                raise InvalidAction('maintain and start must be arrays')
            for mid in a['maintain']:
                integer(mid,0,len(machines)-1,'machine')
            distinct(a['maintain'],'maintenance')
            if len(a['maintain'])+len(a['start']) > len(machines):
                raise InvalidAction('more actions than machines')
            for mid in a['maintain']:
                machine = machines[mid]
                if mid in running or machine['down_until'] > t or spares < 1:
                    raise InvalidAction('maintenance unavailable or no spare')
                machine['down_until'] = t+5
                machine['wear'] = 0
                machine['family'] = None
                spares -= 1
                maintenance += 1
            seen = []
            for start in a['start']:
                exact(start,['job','machine'])
                jid = start['job']
                mid = integer(start['machine'],0,len(machines)-1,'machine')
                if type(jid) is not str or jid not in index:
                    raise InvalidAction('unknown job')
                j, machine = index[jid], machines[mid]
                if (j['release'] > t or state[jid] != 'waiting' or mid in running or
                        machine['down_until'] > t or mid not in j['eligible'] or not all(d in done for d in j['deps'])):
                    raise InvalidAction('job, machine or dependency unavailable')
                if used_power+j['power'] > power_cap or any(inventory[k] < j['consumes'][k] for k in range(3)):
                    raise InvalidAction('power or consumables exceeded')
                seen.append(jid)
                distinct(seen,'job')
                inventory = [inventory[k]-j['consumes'][k] for k in range(3)]
                consumed = [consumed[k]+j['consumes'][k] for k in range(3)]
                duration = math.ceil(j['duration']*machine['speed']*(.75+.5*keyed(seed,'duration',jid,mid)))
                duration += 3 if machine['family'] != j['family'] else 0
                machine['family'] = j['family']
                running[mid] = {'job':jid,'end':t+duration}
                state[jid] = 'running'
                starts += 1
                used_power += j['power']
            for mid in running:
                machines[mid]['wear'] += 1
            energy += used_power
        except InvalidAction as exc:
            error = str(exc)
            break
    weight = sum(j['weight'] for j in jobs)
    tardiness = sum(j['weight']*max(0,done.get(j['id'],instance['horizon']+180)-j['deadline']) for j in jobs)/weight
    missing = sum(j['weight'] for j in jobs if j['id'] not in done)/weight
    loss = tardiness+80*missing+.002*energy+.08*interruptions+.2*maintenance
    return {'valid': error is None, 'loss': loss, 'error': error, 'jobs':len(jobs),
            'completed':len(done),'weighted_tardiness':tardiness,'unfinished_weight_fraction':missing,
            'energy':energy,'starts':starts,'interruptions':interruptions,'maintenance':maintenance,
            'consumed':consumed,'remaining_inventory':inventory}


def evaluate(scale, seed, policy):
    instance = generate(seed+41,scale)
    episodes = 3 if scale == 'full' else 2
    rows = [run_episode(instance,policy,seed+40000+i,i) for i in range(episodes)]
    result = scored(rows,loss_scale=100)
    result['mean_completed'] = sum(r['completed'] for r in rows)/episodes
    return result,[{'name':'jobs_per_episode','legacy':60,'current':len(instance['jobs']),
                    'ratio':len(instance['jobs'])/60,'scope':'executed'},
                   {'name':'machines','legacy':6,'current':len(instance['machines']),
                    'ratio':len(instance['machines'])/6,'scope':'generated'}]


def public(scale):
    return {'task':'R4','jobs_per_episode':720 if scale=='full' else 60,
            'machines':24 if scale=='full' else 6,'horizon':600 if scale=='full' else 120,
            'private':'future arrivals, failure draws, true durations, power and supplies',
            'action':{'maintain':[],'start':[]}}
