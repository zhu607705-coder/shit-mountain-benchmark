#!/usr/bin/env python3
import copy,tempfile,unittest
from pathlib import Path
from judge import evaluate,load_json,validate,upper_tail


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.data=dict(constraints=dict(max_depth=3,max_nodes=20,max_path_cost=5),tests=[dict(id='T',cost=1,delay=0,prerequisites=[],exclusive_group=None,outcomes=['0','1'])],actions=[dict(id='A'),dict(id='B')],objective=dict(tail_mass=.1,tail_coefficient=.45,cost_coefficient=.3,score_scale=35),worlds=[dict(id='W0',weight=1,outcomes={'T':'0'},test_harm={'T':0},delay_loss_per_unit=0,action_losses={'A':0,'B':100}),dict(id='W1',weight=1,outcomes={'T':'1'},test_harm={'T':0},delay_loss_per_unit=0,action_losses={'A':100,'B':0})])
        self.sub=dict(format_version=1,tree=dict(test='T',branches={'0':{'action':'A'},'1':{'action':'B'}}))
    def test_exact_score(self):
        r=evaluate(self.data,self.sub);self.assertEqual(r['metrics']['mean_loss'],0);self.assertAlmostEqual(r['metrics']['objective'],.3);self.assertAlmostEqual(r['raw_score'],1000/(1+.3/35),places=8)
    def test_tail_and_delay(self):
        self.data['tests'][0]['delay']=2;self.data['worlds'][0]['delay_loss_per_unit']=1
        r=evaluate(self.data,self.sub);self.assertEqual(r['metrics']['mean_loss'],1);self.assertEqual(r['metrics']['cvar_worst_10pct_loss'],2)
        self.assertAlmostEqual(upper_tail([(0,9),(10,1)],.2),5)
    def test_missing_branch_unknown_action_extra_key(self):
        s=copy.deepcopy(self.sub);del s['tree']['branches']['0']
        with self.assertRaises(ValueError):validate(self.data,s)
        s=copy.deepcopy(self.sub);s['tree']['branches']['0']['action']='magic'
        with self.assertRaises(ValueError):validate(self.data,s)
        s=copy.deepcopy(self.sub);s['tree']['ground_truth']=1
        with self.assertRaises(ValueError):validate(self.data,s)
    def test_repeated_test(self):
        s=copy.deepcopy(self.sub);s['tree']['branches']['0']=copy.deepcopy(self.sub['tree'])
        with self.assertRaises(ValueError):validate(self.data,s)
    def test_constraints_even_on_unobserved_branch(self):
        self.data['worlds']=self.data['worlds'][:1]
        self.data['tests'].append(dict(id='U',cost=9,delay=0,prerequisites=[],exclusive_group=None,outcomes=['0','1']))
        self.sub['tree']['branches']['1']=dict(test='U',branches={'0':{'action':'A'},'1':{'action':'A'}})
        with self.assertRaises(ValueError):validate(self.data,self.sub)
    def test_prerequisite_and_exclusivity(self):
        self.data['tests'][0]['prerequisites']=['U']
        with self.assertRaises(ValueError):validate(self.data,self.sub)
        self.data['tests'][0]['prerequisites']=[];self.data['tests'][0]['exclusive_group']='G'
        self.data['tests'].append(dict(id='U',cost=1,delay=0,prerequisites=[],exclusive_group='G',outcomes=['0','1']))
        self.sub['tree']['branches']['1']=dict(test='U',branches={'0':{'action':'A'},'1':{'action':'A'}})
        with self.assertRaises(ValueError):validate(self.data,self.sub)
    def test_reject_duplicate_keys_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.json'
            for content in ['{"tree":{},"tree":{}}','{"x":NaN}','{"x":-Infinity}']:
                p.write_text(content)
                with self.assertRaises(ValueError):load_json(p)
    def test_real_baseline(self):
        base=Path(__file__).parent;r=evaluate(load_json(base/'input.json'),load_json(base/'baseline_output.json'));self.assertTrue(r['valid']);self.assertGreater(r['raw_score'],0)
if __name__=='__main__':unittest.main()
