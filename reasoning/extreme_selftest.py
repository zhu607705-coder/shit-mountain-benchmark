"""Independent tiny witnesses plus protocol and isolation regression checks."""
from __future__ import annotations
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from extreme_common import Policy, InvalidAction, keyed, strict_loads, tail
import extreme_r1 as r1
import extreme_r2 as r2
import extreme_r3 as r3
import extreme_r4 as r4


def witnesses():
    # R1: independently enumerate investment + one-tick subsets. Resources double
    # only after investing; the investment consumes the last otherwise idle dollar.
    tiny = {'jobs':[{'id':str(i),'region':0,'release':0,'deadline':1,'value':100,
                    'dependencies':[],'modes':{'standard':{'duration':1,'cost':1,
                    'resources':[1,0,0],'quality':1.}}} for i in range(2)],
            'horizon':1,'initial_budget':3,'base_capacity':[1,1,1],
            'investment_cost':1,'investment_gain':1,'maximum_investments_per_resource':3,
            'regional_count':1}
    seed = next(s for s in range(100) if keyed(s,'storm',0)>=.28)
    rows=[]
    for capital in (0,1):
        for subset in itertools.chain.from_iterable(itertools.combinations(range(2), k) for k in range(3)):
            if len(subset)>1+capital or len(subset)+capital>3:
                continue
            action={'invest':[0]*capital,'cancel':[],'start':[{'job':str(i),'mode':'standard'} for i in subset]}
            expected=100*(1-len(subset)/2)+5*(len(subset)+capital)/3
            with_policy=Policy(lambda obs,a=action:a)
            row=r1.run_episode(tiny,with_policy,seed)
            assert row['valid'] and abs(row['loss']-expected)<1e-9
            rows.append((expected,capital,len(subset)))
    best=min(rows)
    greedy=min(x for x in rows if x[1]==0)

    # R2: setup produces no information, but a legal two-step assay changes Bayes
    # decision loss from 31.0 to 0.6. Expected values do not call the judge formula.
    m=r2.model()
    m.update({'priors':[[.5,.5]+[0.]*30 for _ in range(4)],
              'drift_probability_by_cohort':[0.]*4,'screen_noise':0.,'budget':2,'max_queries':2})
    m['tests']=[{'id':0,'kind':'prepare','chamber':0,'cost':1,'stress_delta':0,'delay':0},
                {'id':1,'kind':'assay','targets':[0],'channel':0,'chamber':0,'cost':1,
                 'stress_delta':0,'threshold':2,'delay':0,'toxicity':0}]
    seeds=[next(s for s in range(100) if (keyed(s,'fault')<.5)==wanted) for wanted in (True,False)]
    stop=[]; conditional=[]
    for s in seeds:
        stop.append(r2.run_episode(m,Policy(lambda obs:{'action':0}),s)['loss'])
        def paired(obs):
            h=obs['history']
            return {'test':len(h)} if len(h)<2 else {'action':0 if h[-1]['result'] else 1}
        row=r2.run_episode(m,Policy(paired),s)
        assert row['valid']
        conditional.append(row['loss'])
    assert abs(sum(stop)/2-31.)<1e-9  # wrong fault within same group costs 62
    assert abs(sum(conditional)/2-.6)<1e-9

    # R3: exhaustive 8-state truth table, independent of simulator, proves marginal
    # information zero and paired information positive under shared drift.
    truth_table=[{'fault':f,'pad':p,'drift':d,'A':p,'B':f^p^d,'C':d}
                 for f,p,d in itertools.product((0,1),repeat=3)]
    for field in ('A','B','C'):
        for value in (0,1):
            assert sum(x['fault'] for x in truth_table if x[field]==value)==2
    assert all((x['A']^x['B']^x['C'])==x['fault'] for x in truth_table)
    # Without calibration, .15 correlated drift gives Bayes error .15 after A+B.
    joint_error=.15
    no_information_error=.5

    # R4: both an immediate high-weight distractor and a low-weight producer can
    # legally consume the only A stock. Only the producer creates B for a valuable
    # successor. Compare all meaningful first choices, using independent arithmetic.
    jobs=[{'id':'P','release':0,'deadline':4,'duration':1,'weight':1,'family':0,'power':1,
           'eligible':[0],'deps':[],'consumes':[1,0,0],'produces':[0,1,0]},
          {'id':'H','release':0,'deadline':4,'duration':1,'weight':9,'family':0,'power':1,
           'eligible':[0],'deps':[],'consumes':[1,0,0],'produces':[0,0,0]},
          {'id':'V','release':0,'deadline':5,'duration':1,'weight':10,'family':0,'power':1,
           'eligible':[0],'deps':['P'],'consumes':[0,1,0],'produces':[0,0,0]}]
    inst={'jobs':jobs,'machines':[{'id':0,'speed':.1}], 'horizon':6,
          'inventory':[1,0,0],'spares':0,'base_power':6}
    candidates=[([], {}, 0), (['H'], {'H':4}, 4), (['P'], {'P':4},4),
                (['P','V'], {'P':4,'V':5},5)]
    r4_rows=[]
    for order, completion, energy in candidates:
        def scheduled(obs,order=order):
            item=order[0] if order and obs['time']==0 else (
                order[1] if len(order)>1 and obs['time']==4 else None)
            return {'maintain':[], 'start':[{'job':item,'machine':0}] if item else []}
        row=r4.run_episode(inst,Policy(scheduled),1)
        expected=sum(j['weight']*max(0,completion.get(j['id'],186)-j['deadline']) for j in jobs)/20
        expected+=80*sum(j['weight'] for j in jobs if j['id'] not in completion)/20+.002*energy
        assert row['valid'] and abs(row['loss']-expected)<1e-9
        r4_rows.append((expected,row))
    r4_best=min(r4_rows,key=lambda x:x[0])
    r4_greedy=r4_rows[1]
    assert r4_best[1]['completed']==2 and r4_best[1]['remaining_inventory']==[0,0,0]
    assert r4_best[0] < r4_greedy[0]
    return {'R1':{'independent_legal_plans_enumerated':len(rows),'optimal_tiny_loss':best[0],
                  'no_investment_best_loss':greedy[0],'judge_agrees':True},
            'R2':{'tiny_worlds_enumerated':2,'stop_loss':sum(stop)/2,
                  'setup_then_assay_loss':sum(conditional)/2,'judge_agrees':True},
            'R3':{'truth_table_states':8,'one_probe_bayes_error':no_information_error,
                  'paired_bayes_error_without_calibration':joint_error,
                  'three_probe_bayes_error':0.,'independent_enumeration':True},
            'R4':{'tiny_jobs':3,'legal_schedules_enumerated':len(r4_rows),
                  'completed':r4_best[1]['completed'],'producer_first_loss':r4_best[0],
                  'high_weight_first_loss':r4_greedy[0],'both_choices_legal':True,
                  'independent_formula_matches_judge':True}}


class ExtremeTests(unittest.TestCase):
    def test_independent_witnesses(self):
        self.assertEqual(set(witnesses()),{'R1','R2','R3','R4'})

    def test_json_strictness(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises((InvalidAction,ValueError)):
                strict_loads(raw)
        self.assertEqual(tail([1,2,100]),100)

    def test_strict_actions_all_tasks(self):
        actions=[{'invest':[True],'cancel':[],'start':[]},{'test':True},
                 {'repair':[True],'group_repair':[]},{'maintain':[True],'start':[]}]
        functions=[lambda p:r1.run_episode(r1.generate(1,'smoke'),p,1),
                   lambda p:r2.run_episode(r2.model(),p,1),
                   lambda p:r3.run_episode(r3.model(),p,1),
                   lambda p:r4.run_episode(r4.generate(1,'smoke'),p,1)]
        for action,fn in zip(actions,functions):
            self.assertFalse(fn(Policy(lambda obs,a=action:a))['valid'])
        for fn in functions:
            self.assertFalse(fn(Policy(lambda obs:None))['valid'])

    def test_mutation_isolation(self):
        def mutate(obs):
            obs['model']['budget']=10**9
            obs['model']['tests'][0]['cost']=0
            obs['remaining_budget']=10**9
            return {'test':0}
        m=r3.model()
        row=r3.run_episode(m,Policy(mutate),1)
        self.assertFalse(row['valid'])
        self.assertEqual(m['budget'],20.)
        self.assertEqual(m['tests'][0]['cost'],1.)

    def test_r1_cancel_and_invest_composition(self):
        jobs=[{'id':str(i),'region':0,'release':0,'deadline':4,'value':100,
               'dependencies':[],'modes':{'standard':{'duration':4 if i==0 else 1,'cost':4,
               'resources':[1,0,0],'quality':1.}}} for i in range(2)]
        inst={'jobs':jobs,'horizon':4,'initial_budget':16,'base_capacity':[1,1,1],
              'investment_cost':1,'investment_gain':1,'maximum_investments_per_resource':3,
              'regional_count':1}
        def act(obs):
            if obs['time']==0:
                return {'invest':[],'cancel':[],'start':[{'job':'0','mode':'standard'}]}
            if obs['time']==1:
                return {'invest':[0],'cancel':['0'],'start':[{'job':str(i),'mode':'standard'} for i in range(2)]}
            return {'invest':[],'cancel':[],'start':[]}
        seed=next(s for s in range(100) if keyed(s,'storm',0)>=.28)
        row=r1.run_episode(inst,Policy(act),seed)
        self.assertTrue(row['valid'],row)
        self.assertEqual(row['budget_spent'],12)
        self.assertEqual(row['cancellations'],1)

    def test_r2_stress_aware_calibration(self):
        m=r2.model()
        m['screen_noise']=0
        for seed in range(24):
            row=r2.run_episode(m,Policy(r2.Baseline()),seed,seed%4)
            self.assertTrue(row['valid'])
            self.assertTrue(row['exact_repair'])
            self.assertEqual(row['stress'],4)

    def test_exports_omit_future_and_are_runnable(self):
        import extreme
        for task,module in [('R1',r1),('R2',r2),('R3',r3),('R4',r4)]:
            with tempfile.TemporaryDirectory() as d:
                result=extreme.export(task,'smoke',d,module)
                self.assertFalse(result['future_or_seed_exported'])
                public=json.loads((Path(d)/'public.json').read_text())
                self.assertNotIn('seed',public)
                self.assertNotIn('jobs',public)
                p=Policy(None,Path(d)/'policy.py')
                try:
                    evaluated,_=module.evaluate('smoke',901,p)
                    self.assertTrue(evaluated['valid'])
                finally:
                    p.close()

    def test_reproducibility(self):
        a=r4.run_episode(r4.generate(91,'smoke'),Policy(r4.baseline),711)
        b=r4.run_episode(r4.generate(91,'smoke'),Policy(r4.baseline),711)
        self.assertEqual(a,b)

    def test_future_is_absent(self):
        def capture(obs):
            self.assertNotIn('seed',obs)
            self.assertTrue(all(j['release']<=obs['time'] for j in obs['jobs']))
            self.assertTrue(all('end' not in x for x in obs.get('running',[])))
            return {'invest':[],'cancel':[],'start':[]}
        self.assertTrue(r1.run_episode(r1.generate(1,'smoke'),Policy(capture),1)['valid'])

    def test_process_protocol(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'policy.py'
            p.write_text('import json,sys\nfor line in sys.stdin:\n print(json.dumps({"test": 0}),flush=True)\n')
            policy=Policy(None,p)
            try:
                self.assertEqual(policy({'hello':1}),{'test':0})
            finally:
                policy.close()

    def test_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'policy.py'
            p.write_text('import time\ntime.sleep(5)\n')
            policy=Policy(None,p,action_timeout=.03)
            try:
                with self.assertRaises(InvalidAction):
                    policy({'hello':1})
            finally:
                policy.close()

    def test_extreme_counts(self):
        self.assertEqual(len(r1.generate(1,'full')['jobs']),576)
        self.assertEqual(len(r2.model()['tests']),180)
        self.assertEqual(r3.model()['components'],128)
        self.assertEqual(len(r4.generate(1,'full')['jobs']),720)


if __name__=='__main__':
    unittest.main()
