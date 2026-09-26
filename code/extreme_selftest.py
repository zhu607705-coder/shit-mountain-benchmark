#!/usr/bin/env python3
"""Judge tests: independent witnesses, real negative controls, and export usability."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from extreme import dimensions, evaluate, export
from extreme_scenarios import scenario, tiny_witnesses, vector_reference, bytes_reference
from extreme_protocol import run as run_protocol, evaluate_module
from extreme_worker import machine_quality

HERE=Path(__file__).resolve().parent


class ExtremeJudgeTests(unittest.TestCase):
    def test_machine_quality_accepts_all_required_gates_without_timing_bonus(self):
        # Simulate compatible legacy checks plus both controls and the new stage composition.
        witness=[{'name':name,'critical':True,'passed':True,'seconds':seconds}
                 for name,seconds in [('legacy_flow',30.0),('stage_control',.001),('stage_composition',900.0)]]
        self.assertEqual(machine_quality(witness),100)
        witness[-1]['seconds']=.000001
        self.assertEqual(machine_quality(witness),100)
        witness[-1]['passed']=False
        self.assertEqual(machine_quality(witness),0)
        self.assertEqual(machine_quality([]),0)

    def test_manual_tiny_witnesses(self):
        self.assertEqual(tiny_witnesses()['vector_sum'],[12,20])
        self.assertEqual(tiny_witnesses()['byte_env_duplicate'],'!z11')

    def test_references_preserve_order_and_repeated_dependencies(self):
        graph={'nodes':{'a':{'op':'input','data':[2]},'b':{'op':'input','data':[3]},
                        'r':{'op':'concat','deps':['b','a','b']}},'aliases':{}}
        self.assertEqual(vector_reference(graph,'r'),[3,2,3])
        files={'nodes':{'a':{'op':'source','path':'a'},'b':{'op':'source','path':'b'},
                        'r':{'op':'concat','deps':['b','a','b'],'separator':'|'}}}
        self.assertEqual(bytes_reference(files,'r',{'a':b'a','b':b'b'},{}),b'b|a|b')

    def test_full_materialized_sizes_have_real_denominators(self):
        for task in ['C1','C2','C3','C4']:
            case=scenario(task,'full',260926)
            dims=dimensions(task,'full')
            self.assertTrue(any(d['ratio']>=10 and d['name'] in case['counts'] for d in dims))
            if task=='C1':self.assertEqual(sum(len(b['events']) for b in case['batches']),128000)
            if task in ('C2','C4'):self.assertEqual(len(case['deep_graph']['nodes']),5000)
            if task=='C3':self.assertEqual(len(case['fault_schedule']),288)

    def test_c3_fault_grid_has_distinct_causal_histories(self):
        case=scenario('C3','full',260926)
        self.assertEqual(len({(x['history'],x['cut'],x['mode']) for x in case['fault_schedule']}),288)
        self.assertEqual(len({t['txid'] for t in case['transactions']}),1440)

    def test_c4_real_wrong_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate=Path(directory)/'engine.py'
            candidate.write_text('class BuildError(RuntimeError): pass\nclass Builder:\n def __init__(self,*a): pass\n def build(self,*a): return b"stale"\n')
            result=evaluate('C4','smoke',260926,candidate)
            self.assertTrue(result['audit_passed'])
            self.assertFalse(result['candidate_result']['valid'])
            self.assertEqual(result['candidate_result']['raw_score'],0)
            failures=[c for c in result['candidate_result']['checks'] if not c['passed']]
            self.assertGreaterEqual(len(failures),2)
            self.assertTrue(any(c['kind']=='interaction' for c in failures))

    def test_c3_broken_starter_has_behavior_failure_and_capability_gap(self):
        result=evaluate('C3','smoke',260926,HERE/'C3'/'starter')
        self.assertTrue(result['audit_passed'])
        self.assertFalse(result['candidate_result']['valid'])
        checks=result['candidate_result']['checks']
        self.assertTrue(any(not c['passed'] and c.get('classification')=='behavior_failure' for c in checks))
        self.assertTrue(any(c.get('classification')=='capability_gap' for c in checks))

    def test_exported_starter_runs_without_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'bundle';manifest=export('C4','smoke',260926,root)
            self.assertTrue((root/'submission'/'engine.py').exists())
            self.assertTrue((root/'scenario.json').exists())
            result=subprocess.run([sys.executable,str(root/'smoke.py')],
                cwd=directory,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout)
            self.assertTrue(report['demo_only'])
            self.assertEqual(manifest['constructed']['nodes'],1200)
            self.assertTrue((root/'submission'/'extreme.py').exists())
            self.assertFalse((root/'judge').exists())
            self.assertFalse(manifest['host_evaluator_included'])
            for path in root.rglob('*'):
                self.assertNotIn(path.name,{'oracle.py','extreme_worker.py','extreme_protocol.py','baseline_full.json','stage_audit.json'})
            contract=(root/'COMPATIBILITY_CONTRACT.md').read_text()
            self.assertEqual(contract,(HERE/'C4'/'LEGACY_PROMPT.md').read_text())
            self.assertNotIn('## 我的基线',contract)

    def test_each_new_stage_has_isolated_success_and_composed_failure(self):
        for task in ['C1','C2','C3','C4']:
            with self.subTest(task=task):
                result=run_protocol(task,HERE/task/'repository'/'baseline' if task in ('C1','C2') else HERE/task/'baseline.py','smoke',260926)
                self.assertTrue(result['audit_passed'])
                self.assertEqual(result['candidate']['status'],'capability_gap')
                self.assertTrue(result['faulty_starter']['controls_passed'])
                self.assertFalse(result['faulty_starter']['composition_passed'])

    def test_supplied_extension_is_evaluated_instead_of_default_starter(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate=Path(directory)/'extreme.py'
            candidate.write_text('class VersionedBuilder:\n def __init__(self,*a): pass\n def update(self,*a): return "x"\n def activate(self,*a): pass\n def build(self,*a,**k): return {"version":"x","data":"wrong"}\n')
            result=evaluate_module('C4',candidate,'smoke',260926)
            self.assertEqual(result['status'],'behavior_failure')
            self.assertFalse(result['controls_passed'])


if __name__=='__main__':unittest.main()
