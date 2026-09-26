"""R1: staged capital planning and nonpreemptive resource scheduling."""
from __future__ import annotations
import math
import random
from extreme_common import InvalidAction, exact, integer, distinct, keyed, scored

FULL_N = 576
MECHANISMS = [
    'Only released contracts and current weather are observable; plans must adapt online.',
    'Irreversible capacity investments compete with project spending and cancellation recourse.',
    'Cross-chain dependencies transmit delivered quality; deadline losses interact with regional fairness.',
    'Correlated weather reduces admission capacity and changes duration/quality at start.']


def generate(seed, scale):
    r = random.Random(seed)
    n, chains, H = (FULL_N, 24, 240) if scale == 'full' else (48, 6, 64)
    jobs = []
    for i in range(n):
        stage, chain = divmod(i, chains)
        release = stage * (6 if scale == 'full' else 4)
        deps = [f'J{i-chains:04d}'] if stage else []
        if stage > 1 and r.random() < .28:
            other = f'J{(stage-1)*chains + r.randrange(chains):04d}'
            if other not in deps:
                deps.append(other)
        demand = [r.randint(1, 3), r.randint(1, 2), r.randint(0, 2)]
        duration = r.randint(3, 8)
        cost = r.randint(4, 10)
        jobs.append({'id': f'J{i:04d}', 'region': chain % 6,
            'release': release, 'deadline': release + r.randint(12, 27),
            'value': r.randint(30, 110), 'dependencies': deps,
            'modes': {
                'standard': {'duration': duration, 'cost': cost, 'resources': demand, 'quality': .97},
                'fast': {'duration': max(1, math.ceil(duration*.55)), 'cost': cost+4,
                         'resources': [x+1 for x in demand], 'quality': .84},
                'careful': {'duration': duration+2, 'cost': cost+2,
                            'resources': demand, 'quality': 1.0}}})
    caps = [16, 13, 12] if scale == 'full' else [8, 7, 6]
    return {'jobs': jobs, 'horizon': H, 'initial_budget': round(n*7.2),
            'base_capacity': caps, 'investment_cost': 65 if scale == 'full' else 22,
            'investment_gain': 4 if scale == 'full' else 2,
            'maximum_investments_per_resource': 3,
            'regional_count': 6}


def baseline(obs):
    # A feasible value-density dispatch rule, without capital search or future access.
    free = obs['free_resources'][:]
    cash = obs['budget']
    ready = [j for j in obs['jobs'] if j['state'] == 'waiting' and
             all(d in obs['completed'] for d in j['dependencies'])]
    ready.sort(key=lambda j: (-j['value']/j['modes']['standard']['duration'], j['id']))
    starts = []
    for j in ready:
        mode = j['modes']['standard']
        if cash >= mode['cost'] and all(free[k] >= mode['resources'][k] for k in range(3)):
            starts.append({'job': j['id'], 'mode': 'standard'})
            cash -= mode['cost']
            free = [free[k]-mode['resources'][k] for k in range(3)]
    return {'invest': [], 'cancel': [], 'start': starts}


def run_episode(instance, policy, seed, episode=0):
    jobs = instance['jobs']
    index = {j['id']: j for j in jobs}
    state = {j['id']: 'waiting' for j in jobs}
    running, done = {}, {}
    budget = instance['initial_budget']
    invested = [0, 0, 0]
    spent = 0
    cancellations = 0
    timeline = []
    error = None
    for t in range(instance['horizon']+1):
        for jid in list(running):
            work = running[jid]
            if work['end'] <= t:
                job = index[jid]
                quality = work['quality']
                revenue = job['value']*quality*max(0., 1-max(0,t-job['deadline'])/24)
                done[jid] = {'time': t, 'quality': quality, 'reward': revenue}
                state[jid] = 'done'
                del running[jid]
        if t == instance['horizon']:
            break
        # A block's weather is hidden until its first tick; no future table is exposed.
        storm = keyed(seed, 'storm', t//8) < .28
        caps = [max(1, cap+instance['investment_gain']*invested[k]-(3 if storm else 0))
                for k, cap in enumerate(instance['base_capacity'])]
        used = [sum(x['resources'][k] for x in running.values()) for k in range(3)]
        free = [max(0, caps[k]-used[k]) for k in range(3)]
        visible = [dict(j, state=state[j['id']]) for j in jobs if j['release'] <= t]
        obs = {'task': 'R1', 'reset': t == 0, 'episode': episode, 'time': t,
               'horizon': instance['horizon'], 'jobs': visible,
               'completed': done, 'running': [{k:v for k,v in x.items() if k != 'end'} |
                                              {'job': jid} for jid,x in running.items()],
               'budget': budget, 'free_resources': free, 'weather': 'storm' if storm else 'clear',
               'investments': invested, 'investment_cost': instance['investment_cost'],
               'investment_gain': instance['investment_gain'], 'maximum_investments': 3}
        try:
            action = policy(obs)
            exact(action, ['invest', 'cancel', 'start'])
            if any(type(action[k]) is not list for k in action):
                raise InvalidAction('invest, cancel and start must be arrays')
            if len(action['start']) > len(jobs) or len(action['cancel']) > len(running):
                raise InvalidAction('oversized action')
            for resource in action['invest']:
                integer(resource, 0, 2, 'resource')
                cost = instance['investment_cost']
                if invested[resource] >= 3 or budget < cost:
                    raise InvalidAction('investment exceeds cap or budget')
                invested[resource] += 1
                budget -= cost
                spent += cost
                free[resource] += instance['investment_gain']
            if any(type(jid) is not str for jid in action['cancel']):
                raise InvalidAction('cancel entries must be job strings')
            distinct(action['cancel'], 'cancellation')
            for jid in action['cancel']:
                if jid not in running:
                    raise InvalidAction('only running jobs may be cancelled')
                work = running.pop(jid)
                # Paid once per attempt; half of the still-unfinished portion is refunded.
                refund = math.floor(work['cost']*.5*(work['end']-t)/(work['end']-work['start']))
                budget += refund
                spent -= refund
                free = [max(0, instance['base_capacity'][k]+instance['investment_gain']*invested[k]-
                            (3 if storm else 0)-sum(x['resources'][k] for x in running.values()))
                        for k in range(3)]
                state[jid] = 'waiting'
                cancellations += 1
            seen = []
            for item in action['start']:
                exact(item, ['job', 'mode'])
                jid, mode_name = item['job'], item['mode']
                if type(jid) is not str or type(mode_name) is not str or jid not in index:
                    raise InvalidAction('unknown job or mode')
                j = index[jid]
                if mode_name not in j['modes']:
                    raise InvalidAction('unknown mode')
                if j['release'] > t or state[jid] != 'waiting' or not all(d in done for d in j['dependencies']):
                    raise InvalidAction('job unavailable or dependency unfinished')
                mode = j['modes'][mode_name]
                if budget < mode['cost'] or any(free[k] < mode['resources'][k] for k in range(3)):
                    raise InvalidAction('resource or money oversubscription')
                seen.append(jid)
                distinct(seen, 'start')
                budget -= mode['cost']
                spent += mode['cost']
                free = [free[k]-mode['resources'][k] for k in range(3)]
                duration = math.ceil(mode['duration']*(1.5 if storm else 1))
                quality = mode['quality']*(.91 if storm else 1)*min(
                    [done[d]['quality'] for d in j['dependencies']] or [1])
                running[jid] = {'start': t, 'end': t+duration, 'cost': mode['cost'],
                                'quality': quality, 'resources': mode['resources'][:]}
                state[jid] = 'running'
            if any(action.values()):
                timeline.append({'time': t, 'action': action, 'remaining_budget': budget})
        except InvalidAction as exc:
            error = str(exc)
            break
    value = sum(j['value'] for j in jobs)
    reward = sum(x['reward'] for x in done.values())
    regional = []
    for region in range(instance['regional_count']):
        total = sum(j['value'] for j in jobs if j['region'] == region)
        got = sum(done[j['id']]['reward'] for j in jobs if j['region'] == region and j['id'] in done)
        regional.append(got/total if total else 1.)
    coverage = reward/value
    fairness = min(regional)
    # A fixed reference loss, not a precomputed optimum or author-normalized ceiling.
    loss = 100*(1-(.75*coverage+.25*fairness)) + 5*spent/instance['initial_budget']
    return {'valid': error is None, 'loss': loss, 'error': error, 'completed': len(done),
            'jobs': len(jobs), 'coverage': coverage, 'minimum_region_coverage': fairness,
            'budget_spent': spent, 'investments': invested, 'cancellations': cancellations,
            'timeline_sha256': __import__('hashlib').sha256(__import__('json').dumps(timeline,sort_keys=True).encode()).hexdigest()}


def evaluate(scale, seed, policy):
    instance = generate(seed+11, scale)
    episodes = 4 if scale == 'full' else 2
    rows = [run_episode(instance, policy, seed+100+i, i) for i in range(episodes)]
    result = scored(rows, loss_scale=50)
    result['mean_completed'] = sum(x['completed'] for x in rows)/episodes
    return result, [{'name': 'jobs_per_episode', 'legacy': 48, 'current': len(instance['jobs']),
                     'ratio': len(instance['jobs'])/48, 'scope': 'executed'}]


def public(scale):
    return {'task': 'R1', 'jobs_per_episode': FULL_N if scale == 'full' else 48,
            'horizon': 240 if scale == 'full' else 64,
            'job_arrivals': 'staged, details disclosed only at release',
            'weather': {'block_ticks': 8, 'storm_probability': .28},
            'action': {'invest': [], 'cancel': [], 'start': []}}
