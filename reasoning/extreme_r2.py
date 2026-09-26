"""R2: interventions affect later measurements; latent drift is correlated."""
from __future__ import annotations
import math
import random
from extreme_common import InvalidAction, exact, integer, keyed, scored

MECHANISMS = [
    'Assays require irreversible chamber preparation, so zero-information setup can unlock later value.',
    'Calibration and preparation change stress; stress changes subsequent observation equations and treatment harm.',
    'Latent channel drift correlates cheap sensors; public cohort priors differ, with pooled upper-tail loss.',
    'Different assays trade decision information against class-specific toxic side effects.']


def model():
    tests = []
    for bit in range(5):
        tests.append({'id': len(tests), 'kind': 'screen', 'bit': bit, 'channel': bit % 4,
                      'cost': 1, 'stress_delta': 0, 'delay': 1})
    for channel in range(4):
        tests.append({'id': len(tests), 'kind': 'calibrate', 'channel': channel,
                      'cost': 2, 'stress_delta': 1, 'delay': 1})
    for chamber in range(4):
        tests.append({'id': len(tests), 'kind': 'prepare', 'chamber': chamber,
                      'cost': 1, 'stress_delta': chamber % 2, 'delay': 1})
    r = random.Random(8841)  # Public assay dictionary, independent of episode seeds.
    for idx in range(167):
        targets = sorted(r.sample(range(32), 2 + idx % 15))
        tests.append({'id': len(tests), 'kind': 'assay', 'targets': targets,
                      'channel': idx % 4, 'chamber': (idx // 4) % 4,
                      'cost': 1 + idx % 4, 'stress_delta': int(idx % 3 == 0),
                      'threshold': 2 + idx % 5, 'delay': 1 + idx % 2,
                      'toxicity': 2 + idx % 7})
    return {'tests': tests, 'faults': 32, 'channels': 4, 'budget': 16,
            'max_queries': 12, 'screen_noise': .04,
            'drift_probability_by_cohort': [.08, .16, .24, .32],
            'actions': {'targeted': list(range(32)), 'broad': [32,33,34,35], 'shutdown': 36},
            'priors': [[(3 if f//8 == cohort else 1)/48 for f in range(32)] for cohort in range(4)]}


def signal(test, fault, drift, stress):
    kind = test['kind']
    if kind == 'prepare':
        return 0
    d = (drift >> test['channel']) & 1
    if kind == 'calibrate':
        return d ^ (stress % 2)
    if kind == 'screen':
        return ((fault >> test['bit']) & 1) ^ d ^ (stress % 2)
    return int(fault in test['targets']) ^ d ^ int(stress >= test['threshold'])


def treatment_loss(action, fault, stress):
    if action < 32:
        base = 0 if action == fault else (105 if action//8 != fault//8 else 62)
        return base + stress * (1 if action == fault else 3)
    if action < 36:
        return (20 if action-32 == fault//8 else 100) + 2*stress
    return 73 + .4*stress


class Baseline:
    """Fixed calibrated-screen strategy with exact finite posterior at stopping.

    Uses all 512 public fault/drift hypotheses; it does not search assay prerequisites.
    """
    def __init__(self):
        self.model = model()

    def __call__(self, obs):
        if obs.get('model'):
            self.model = obs['model']
        history = obs['history']
        # Calibration shifts stress, so subsequent screen readings must be normalized.
        order = [5, 0, 6, 1, 7, 2, 8, 3, 4]
        if len(history) < len(order):
            test_id = order[len(history)]
            if self.model['tests'][test_id]['cost'] <= obs['remaining_budget']:
                return {'test': test_id}
        cohort = obs['cohort']
        p = self.model['drift_probability_by_cohort'][cohort]
        posterior = [0.]*32
        for fault in range(32):
            for drift in range(16):
                w = self.model['priors'][cohort][fault]*p**drift.bit_count()*(1-p)**(4-drift.bit_count())
                for h in history:
                    test = self.model['tests'][h['test']]
                    expected = signal(test, fault, drift, h['stress_before'])
                    noise = self.model['screen_noise'] if test['kind'] in ('screen','assay') else 0
                    w *= 1-noise if expected == h['result'] else noise
                posterior[fault] += w
        best = min(range(37), key=lambda a: sum(posterior[f]*treatment_loss(a,f,obs['stress']) for f in range(32)))
        return {'action': best}


baseline = Baseline()


def run_episode(m, policy, seed, episode=0):
    cohort = episode % 4
    u = keyed(seed, 'fault')
    cumulative = 0.
    fault = 31
    for f, probability in enumerate(m['priors'][cohort]):
        cumulative += probability
        if u < cumulative:
            fault = f
            break
    drift = sum((keyed(seed, 'drift', k) < m['drift_probability_by_cohort'][cohort]) << k for k in range(4))
    history, used = [], set()
    budget, stress, side_effect, delay = m['budget'], 0, 0., 0
    chamber = None
    for turn in range(m['max_queries']+1):
        obs = {'task': 'R2', 'reset': turn == 0, 'episode': episode, 'cohort': cohort,
               'history': history, 'remaining_budget': budget, 'stress': stress,
               'prepared_chamber': chamber, 'max_queries': m['max_queries']}
        if turn == 0:
            obs['model'] = m
        try:
            a = policy(obs)
            if type(a) is not dict or set(a) not in ({'test'}, {'action'}):
                raise InvalidAction('expected exactly test or action')
            if 'action' in a:
                act = integer(a['action'], 0, 36, 'terminal action')
                terminal = treatment_loss(act, fault, stress)
                loss = terminal + side_effect + .6*delay + .3*(m['budget']-budget)
                return {'valid': True, 'loss': loss, 'cohort': cohort, 'queries': len(history),
                        'terminal_action': act, 'terminal_loss': terminal,
                        'side_effect': side_effect, 'stress': stress, 'budget_spent': m['budget']-budget,
                        'history': history, 'exact_repair': act == fault}
            j = integer(a['test'], 0, len(m['tests'])-1, 'test')
            test = m['tests'][j]
            if j in used or turn == m['max_queries'] or budget < test['cost']:
                raise InvalidAction('repeated/excess/over-budget test')
            if test['kind'] == 'prepare' and chamber is not None:
                raise InvalidAction('chamber preparation is irreversible and exclusive')
            if test['kind'] == 'assay' and chamber != test['chamber']:
                raise InvalidAction('assay needs its prepared chamber')
            outcome = signal(test, fault, drift, stress)
            if test['kind'] in ('screen', 'assay') and keyed(seed, 'measurement', j) < m['screen_noise']:
                outcome ^= 1
            if test['kind'] == 'assay':
                side_effect += test['toxicity']*(1 + 2*int(fault in test['targets']))
            if test['kind'] == 'prepare':
                chamber = test['chamber']
            history.append({'test': j, 'result': outcome, 'stress_before': stress})
            stress += test['stress_delta']
            budget -= test['cost']
            delay += test['delay']
            used.add(j)
        except InvalidAction as exc:
            return {'valid': False, 'loss': 250., 'cohort': cohort, 'error': str(exc),
                    'queries': len(history), 'history': history, 'exact_repair': False}
    raise AssertionError('unreachable')


def evaluate(scale, seed, policy):
    m = model()
    n = 1800 if scale == 'full' else 24
    rows = [run_episode(m, policy, seed+10000+i, i) for i in range(n)]
    result = scored(rows, loss_scale=50)
    result['exact_repair_rate'] = sum(r['exact_repair'] for r in rows)/n
    result['cohort_mean_losses'] = [sum(r['loss'] for r in rows if r['cohort']==c)/
                                    sum(r['cohort']==c for r in rows) for c in range(4)]
    return result, [
        {'name': 'evaluated_worlds', 'legacy': 180, 'current': n, 'ratio': n/180, 'scope': 'executed'},
        {'name': 'distinct_available_tests', 'legacy': 18, 'current': len(m['tests']),
         'ratio': len(m['tests'])/18, 'scope': 'generated'}]


def public(scale):
    return {'task': 'R2', 'model': model(), 'worlds': 1800 if scale == 'full' else 24,
            'private': 'fault, channel drift, per-assay noise; never included in observations'}
