#!/usr/bin/env python3
"""Organizer regression checks for the R3/R4/scoring boundary."""
import copy,hashlib,importlib.util,math,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[2]

def load(relative,name):
    spec=importlib.util.spec_from_file_location(name,BASE/relative);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
r1=load('reasoning/R3/evaluator.py','review_r1');r2=load('reasoning/R4/evaluator.py','review_r2');scoring=load('organizer/quality_math.py','review_scoring')

class Fixed:
    def __init__(self,value):self.value=value
    def act(self,*args):return copy.deepcopy(self.value)

class Boundaries(unittest.TestCase):
    def test_r1_model_mutation_does_not_change_loss(self):
        model=r1.make_model();saved=copy.deepcopy(model)
        class Mutator:
            def act(self,m,h,b):m['terminal_losses'][0]=[0]*len(m['hypotheses']);m['budget']=999;return {'repair':[]}
        observed=r1.run_case(model,Mutator(),90000);expected=r1.run_case(model,Fixed({'repair':[]}),90000)
        self.assertEqual(observed,expected);self.assertEqual(model,saved);self.assertGreater(observed['loss'],0)
    def test_r1_history_mutation_does_not_erase_cost_or_queries(self):
        class Mutator:
            def act(self,m,h,b):
                if not h:return {'test':0}
                h.clear();return {'repair':[]}
        result=r1.run_case(r1.make_model(),Mutator(),90000)
        self.assertTrue(result['valid']);self.assertEqual(result['queries'],1);self.assertGreater(result['cost'],0)
    def test_r1_strict_actions(self):
        for action in [None,[],{}, {'test':True},{'test':0.0},{'test':float('nan')},{'test':float('inf')},{'repair':[True]},{'repair':[1.0]},{'repair':[float('nan')]},{'repair':[1,1]},{'repair':[],'test':0}]:
            with self.subTest(action=action):self.assertFalse(r1.run_case(r1.make_model(),Fixed(action),90000)['valid'])
    def test_r1_exceptions_are_invalid(self):
        class Raises:
            def act(self,*args):raise RuntimeError('failed policy')
        result=r1.run_case(r1.make_model(),Raises(),90000);self.assertFalse(result['valid']);self.assertIn('RuntimeError',result['error'])
    def test_r1_budget_cannot_be_changed(self):
        class Spend:
            def act(self,m,h,b):
                m['budget']=999
                return {'test':max(range(len(m['tests'])),key=lambda j:m['tests'][j]['cost'])}
        result=r1.run_case(r1.make_model(),Spend(),90000);self.assertFalse(result['valid']);self.assertIn(result['error'],['over budget','invalid/excess query'])
    def test_r1_common_random_numbers_ignore_query_order(self):
        class Sequence:
            def __init__(self,order):self.order=order
            def act(self,m,h,b):return {'test':self.order[len(h)]} if len(h)<len(self.order) else {'repair':[]}
        a=r1.run_case(r1.make_model(),Sequence([0,1]),90000);b=r1.run_case(r1.make_model(),Sequence([1,0]),90000)
        self.assertEqual({x['test']:x['positive'] for x in a['history']},{x['test']:x['positive'] for x in b['history']})
    def test_r1_alternate_seed_parameters_are_recorded(self):
        a=r1.evaluate(Fixed({'repair':[]}),models=1,episodes=2,model_seed=123,episode_seed=456)
        self.assertTrue(a['valid']);self.assertFalse(a['sampling']['public_default_seeds']);self.assertEqual(a['episodes'],2)
    def test_r2_nested_observation_is_detached(self):
        original=r2.generate;captured={}
        def wrapped(seed):
            result=original(seed);captured['host']=result[0];captured['before']=copy.deepcopy(result[0]);return result
        class Mutator:
            def act(self,observation):
                for job in observation['jobs']:job['deps'].clear();job['eligible'].clear()
                return []
        try:r2.generate=wrapped;r2.run_case(Mutator(),72000)
        finally:r2.generate=original
        self.assertEqual(captured['before'],captured['host'])
    def test_r2_strict_actions(self):
        for actions in [None,{},[None],[{'job':[],'machine':0}],[{'job':'J000','machine':True}],[{'job':'J000','machine':0.0}],[{'job':'J000','machine':float('nan')}],[{'job':'J000','machine':float('inf')}],[{'job':'J000','machine':0,'extra':1}]]:
            with self.subTest(actions=actions):self.assertFalse(r2.run_case(Fixed(actions),72000)['valid'])
    def test_r2_policy_exception_is_invalid(self):
        class Raises:
            def act(self,*args):raise RuntimeError('failed dispatcher')
        result=r2.run_case(Raises(),72000);self.assertFalse(result['valid']);self.assertIn('RuntimeError',result['errors'][0])
    def test_r2_no_future_fields_in_observation(self):
        class Observer:
            def act(self,o):
                assert all(j['release']<=o['time'] for j in o['jobs'])
                assert set(o)=={'time','jobs','done','horizon','free_power','machines'}
                assert all('end' not in m and 'outages' not in m for m in o['machines'])
                return []
        self.assertTrue(r2.run_case(Observer(),72000)['valid'])
    def test_fractional_tail_is_exact_for_nonmultiple_of_ten(self):
        expected=(20+19+.1*18)/2.1
        self.assertAlmostEqual(r1._upper_tail(list(range(21))),expected)
        self.assertAlmostEqual(r2._upper_tail(list(range(21))),expected)
    def test_scoring_rejects_booleans_nonfinite_duplicate_names(self):
        for value in [True,False,float('nan'),float('inf'),-1,'0.5',10**1000]:
            with self.subTest(value=repr(value)[:30]):
                with self.assertRaises(ValueError):scoring.relative_scores([{'name':'x','quality':value,'eligible':True}])
        for loss,scale in [(True,10),(1,True),(float('nan'),10),(1,0)]:
            with self.assertRaises(ValueError):scoring.quality_from_loss(loss,scale)
        with self.assertRaises(ValueError):scoring.relative_scores([{'name':'same','quality':.5,'eligible':True}]*2)
    def test_scoring_valid_examples_and_no_winner(self):
        result=scoring.relative_scores([{'name':'a','quality':.8,'eligible':True},{'name':'b','quality':.6,'eligible':True},{'name':'c','quality':1,'eligible':False}])
        self.assertEqual([r['relative_score'] for r in result],[100,75,0]);self.assertEqual(scoring.relative_scores([]),[])
        self.assertFalse(scoring.relative_scores([{'name':'x','quality':0,'eligible':True}])[0]['leaderboard_has_winner'])
if __name__=='__main__':unittest.main()
