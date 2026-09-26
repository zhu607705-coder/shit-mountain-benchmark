import copy
import json
import unittest
from arena import rules


class RuleTests(unittest.TestCase):
    def test_catalog_complete_and_tiers_are_actual_scopes(self):
        data=rules.catalog();self.assertEqual(len(data['tasks']),12);self.assertEqual(len(data['tiers']),6)
        for task in rules.TASKS:
            draws=[rules.draw_spec(task,t['id'],42)['public'] for t in rules.TIERS]
            self.assertEqual(len({d['scope_id'] for d in draws}),6)
            self.assertEqual([d['fixture_scale'] for d in draws],['smoke']*3+['full']*3)
            self.assertEqual([d['cases'] for d in draws],[1,1,2,1,3,5])
        self.assertFalse(rules.scope_for('C1','silver')['require_stage_v2'])
        self.assertTrue(rules.scope_for('C1','gold')['require_stage_v2'])

    def test_reproducible_draw_no_private_seed_in_public(self):
        a=rules.draw_spec('R3','王者',8821);b=rules.draw_spec('R3','king',8821)
        self.assertEqual(a,b)
        self.assertEqual(len(a['private']['case_seeds']),3)
        encoded=json.dumps(a['public'])
        for value in a['private']['case_seeds']:self.assertNotIn(str(value),encoded)
        self.assertNotIn('case_seeds',a['public']);self.assertNotIn('seed',a['public'])
        self.assertNotEqual(rules.draw_spec('R3','king')['public']['commitment'],rules.draw_spec('R3','king')['public']['commitment'])

    def test_scope_and_seeds_are_committed(self):
        private=rules.draw_spec('F1','bronze',1)['private'];rules.validate_private(private)
        changed=copy.deepcopy(private);changed['case_seeds'][0]+=1
        with self.assertRaises(ValueError):rules.validate_private(changed)
        changed=copy.deepcopy(private);changed['scope']['selector']['names']=[]
        with self.assertRaises(ValueError):rules.validate_private(changed)
        changed=copy.deepcopy(private);changed['budgets']['total_ms']=1
        with self.assertRaises(ValueError):rules.validate_private(changed)
        for field in ('prompt','materials','deliverables','budget'):
            changed=copy.deepcopy(private);changed['prompt_segments'][0][field]='forged'
            with self.assertRaises(ValueError):rules.validate_private(changed)
        changed=copy.deepcopy(private);changed['efficiency_profile']='time_tokens'
        with self.assertRaises(ValueError):rules.validate_private(changed)
        changed=copy.deepcopy(private);changed['public_spec']['prompt_segments'][0]['prompt']='forged'
        with self.assertRaises(ValueError):rules.validate_private(changed)

    def test_three_segments_have_distinct_scope_materials_and_deliverables(self):
        public=rules.draw_spec('C4','silver',10)['public'];segments=public['prompt_segments']
        self.assertEqual(len(segments),3)
        self.assertEqual(len({s['scope'] for s in segments}),3)
        self.assertEqual(len({tuple(s['materials']) for s in segments}),3)
        self.assertEqual(len({tuple(s['deliverables']) for s in segments}),3)
        self.assertEqual(sum(s['budget']['total_ms'] for s in segments),public['budgets']['total_ms'])

    def test_unknown_task_tier_and_boolean_seed_rejected(self):
        for args in [('X1','gold',1),('R1','unknown',1),('R1','gold',True)]:
            with self.assertRaises(ValueError):rules.draw_spec(*args)


if __name__=='__main__':unittest.main()
