#!/usr/bin/env python3
import copy,json,tempfile,unittest
from pathlib import Path
from judge import evaluate,load_json,validate,lower_tail


class JudgeTests(unittest.TestCase):
    def setUp(self):
        mode=dict(id='standard',cost=1,duration=2,resources=[1,0,0],quality=1)
        tasks=[dict(id=k,region='G',zone='Z',value=10,release=0,deadline=4,mandatory=True,dependencies=[],modes=[mode]) for k in ['A','B']]
        self.data=dict(horizon=4,budget=2,regions=['G'],tasks=tasks,scenarios=[dict(id='S',weight=1,capacity=[[1,0,0]]*4,duration_factor={'A':1,'B':1},quality_factor={'A':1,'B':1})])
        self.sub=dict(format_version=1,plan=[dict(task=k,mode='standard') for k in ['A','B']])
    def test_exact_score_and_zone_schedule(self):
        result=evaluate(self.data,self.sub);self.assertEqual(result['raw_score'],950);self.assertEqual([(r['start'],r['end']) for r in result['scenarios'][0]['schedule']],[(0,2),(2,4)])
    def test_outage_and_unscheduled_penalty(self):
        self.data['scenarios'][0]['capacity'][0]=[0,0,0]
        result=evaluate(self.data,self.sub);self.assertEqual(result['raw_score'],450);self.assertEqual(result['scenarios'][0]['unscheduled'],1)
    def test_invalid_variants(self):
        variants=[]
        s=copy.deepcopy(self.sub);s['plan']=[];variants.append(s)
        s=copy.deepcopy(self.sub);s['plan'][1]['task']='A';variants.append(s)
        s=copy.deepcopy(self.sub);s['plan'][0]['mode']='magic';variants.append(s)
        s=copy.deepcopy(self.sub);s['format_version']=True;variants.append(s)
        s=copy.deepcopy(self.sub);s['bonus']=99;variants.append(s)
        for s in variants:
            with self.assertRaises(ValueError):validate(self.data,s)
        self.data['budget']=1
        with self.assertRaises(ValueError):validate(self.data,self.sub)
    def test_dependency_order(self):
        self.data['tasks'][0]['dependencies']=['B']
        with self.assertRaises(ValueError):validate(self.data,self.sub)
    def test_fractional_tail(self):self.assertAlmostEqual(lower_tail([(0,1),(1,9)],.2),.5)
    def test_reject_duplicate_keys_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.json'
            for content in ['{"format_version":1,"format_version":1}', '{"x":NaN}', '{"x":Infinity}']:
                p.write_text(content)
                with self.assertRaises(ValueError):load_json(p)
    def test_real_baseline_and_resource_replay(self):
        base=Path(__file__).parent;data=load_json(base/'input.json');sub=load_json(base/'baseline_output.json');result=evaluate(data,sub)
        self.assertTrue(result['valid']);tasks={t['id']:t for t in data['tasks']};modes={x['task']:next(m for m in tasks[x['task']]['modes'] if m['id']==x['mode']) for x in sub['plan']}
        for sc,row in zip(data['scenarios'],result['scenarios']):
            for tick in range(data['horizon']):
                active=[x for x in row['schedule'] if 'start' in x and x['start']<=tick<x['end']]
                self.assertEqual(len(active),len({tasks[x['task']]['zone'] for x in active}))
                for j in range(3):self.assertLessEqual(sum(modes[x['task']]['resources'][j] for x in active),sc['capacity'][tick][j])
if __name__=='__main__':unittest.main()
