"""R3: complementary probes, common-cause noise and constrained repair."""
from __future__ import annotations
from extreme_common import InvalidAction, integer, distinct, keyed, scored

BITS = 6
N = 2*(2**BITS)
MECHANISMS = [
    'A pad probe and a masked probe have zero marginal information but reveal a fault bit jointly.',
    'Pads and drift are shared across two fault slots; additional measurements are conditionally correlated.',
    'Calibration competes with diagnosis under one budget; repeated probes do not resample noise.',
    'Two simultaneous faults have different miss costs; exact repairs compete with expensive group repair.']


def model():
    tests = []
    for b in range(BITS):
        tests.append({'id': len(tests), 'kind': 'pad', 'bit': b, 'cost': 1.0})
    for slot in range(2):
        for b in range(BITS):
            tests.append({'id': len(tests), 'kind': 'masked', 'slot': slot, 'bit': b, 'cost': 1.0})
    for b in range(BITS):
        tests.append({'id': len(tests), 'kind': 'calibrate', 'bit': b, 'cost': 1.5})
    for component in range(N):
        tests.append({'id': len(tests), 'kind': 'direct', 'component': component, 'cost': 2.5})
    return {'components': N, 'slots': 2, 'bits_per_slot': BITS, 'tests': tests,
            'max_queries': 20, 'budget': 20., 'repair_capacity': 2,
            'drift_probability': .15, 'direct_true_probability': .80,
            'direct_false_probability': .12, 'miss_costs': [120., 70.],
            'exact_repair_cost': 4., 'false_repair_cost': 18.,
            'group_repair_cost': 54., 'group_repair_capacity': 2,
            'prior': 'one uniform fault in each disjoint group of 64'}


class Baseline:
    """Pairs all bits for the larger-risk slot, then calibrates as budget allows."""
    def __call__(self, obs):
        history = obs['history']
        order = [x for b in range(BITS) for x in (b, BITS+b)] + list(range(3*BITS,4*BITS))
        used = {x['test']: x['result'] for x in history}
        for j in order:
            cost = 1.5 if j >= 3*BITS else 1.
            if j not in used and cost <= obs['remaining_budget']:
                return {'test': j}
        component = 0
        for b in range(BITS):
            bit = used.get(b, 0) ^ used.get(BITS+b, 0) ^ used.get(3*BITS+b, 0)
            component |= bit << b
        # A second blind exact repair costs more in expectation than it avoids.
        return {'repair': [component], 'group_repair': []}


baseline = Baseline()


def run_episode(m, policy, seed, episode=0):
    truth = [int(keyed(seed, 'fault', slot)*64) + slot*64 for slot in range(2)]
    pads = [int(keyed(seed, 'pad', b)*2) for b in range(BITS)]
    drift = [int(keyed(seed, 'drift', b) < m['drift_probability']) for b in range(BITS)]
    # One shared uniform error draw per group correlates every direct probe in that group.
    direct_u = [keyed(seed, 'direct-noise', slot) for slot in range(2)]
    history, used = [], set()
    budget = m['budget']
    for turn in range(m['max_queries']+1):
        obs = {'task': 'R3', 'reset': turn == 0, 'episode': episode,
               'history': history, 'remaining_budget': budget, 'max_queries': m['max_queries']}
        if turn == 0:
            obs['model'] = m
        try:
            a = policy(obs)
            if type(a) is not dict or set(a) not in ({'test'}, {'repair','group_repair'}):
                raise InvalidAction('expected test or repair and group_repair')
            if 'repair' in a:
                repairs, groups = a['repair'], a['group_repair']
                if type(repairs) is not list or type(groups) is not list:
                    raise InvalidAction('repair fields must be arrays')
                for c in repairs:
                    integer(c, 0, N-1, 'component')
                for g in groups:
                    integer(g, 0, 1, 'group')
                distinct(repairs, 'component')
                distinct(groups, 'group')
                if len(repairs)+2*len(groups) > m['repair_capacity']:
                    raise InvalidAction('repair crew capacity exceeded')
                if any(c//64 in groups for c in repairs):
                    raise InvalidAction('overlapping exact and group repair')
                missed = [slot for slot in range(2) if truth[slot] not in repairs and slot not in groups]
                terminal = sum(m['miss_costs'][s] for s in missed)
                terminal += len(repairs)*m['exact_repair_cost'] + len(groups)*m['group_repair_cost']
                terminal += sum(c not in truth for c in repairs)*m['false_repair_cost']
                return {'valid': True, 'loss': terminal+m['budget']-budget,
                        'queries': len(history), 'budget_spent': m['budget']-budget,
                        'repair': repairs, 'group_repair': groups, 'missed_faults': len(missed),
                        'exact_both': set(repairs)==set(truth), 'history': history}
            j = integer(a['test'], 0, len(m['tests'])-1, 'test')
            test = m['tests'][j]
            if j in used or turn == m['max_queries'] or budget < test['cost']:
                raise InvalidAction('repeated/excess/over-budget test')
            b = test.get('bit')
            if test['kind'] == 'pad':
                result = pads[b]
            elif test['kind'] == 'masked':
                result = ((truth[test['slot']] % 64 >> b) & 1) ^ pads[b] ^ drift[b]
            elif test['kind'] == 'calibrate':
                result = drift[b]
            else:
                c = test['component']
                result = int(direct_u[c//64] < (m['direct_true_probability'] if c in truth else m['direct_false_probability']))
            history.append({'test': j, 'result': result})
            used.add(j)
            budget -= test['cost']
        except InvalidAction as exc:
            return {'valid': False, 'loss': 300., 'error': str(exc), 'queries': len(history),
                    'missed_faults': 2, 'exact_both': False, 'history': history}
    raise AssertionError('unreachable')


def evaluate(scale, seed, policy):
    m = model()
    n = 960 if scale == 'full' else 16
    rows = [run_episode(m, policy, seed+30000+i, i) for i in range(n)]
    result = scored(rows, loss_scale=50)
    result['both_faults_repaired_rate'] = sum(r['exact_both'] for r in rows)/n
    result['mean_missed_faults'] = sum(r['missed_faults'] for r in rows)/n
    return result, [
        {'name': 'components', 'legacy': 10, 'current': N, 'ratio': N/10, 'scope': 'generated'},
        {'name': 'episodes', 'legacy': 90, 'current': n, 'ratio': n/90, 'scope': 'executed'}]


def public(scale):
    return {'task': 'R3', 'model': model(), 'episodes': 960 if scale == 'full' else 16,
            'private': 'two faults, pads, shared drift and shared direct-probe noise'}
