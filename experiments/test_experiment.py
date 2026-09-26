from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

MODULE=Path(__file__).resolve().parents[1]/'scripts'/'experiment.py'
spec=importlib.util.spec_from_file_location('experiment',MODULE)
e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
EFFICIENCY=MODULE.parents[1]/'organizer'/'efficiency.py'
eff_spec=importlib.util.spec_from_file_location('experiment_efficiency_test',EFFICIENCY)
eff=importlib.util.module_from_spec(eff_spec);eff_spec.loader.exec_module(eff)


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.patch=mock.patch.object(e,'ROOT',self.root);self.patch.start()
        self.plan={'id':'demo','tasks':['R3','F1'],'scale':'smoke','rounds':2,
                   'prompt_variants':[{'id':'direct','text':'read and solve'},
                                      {'id':'hypothesis','text':'reproduce then solve'},
                                      {'id':'adversarial','text':'solve and challenge'}],
                   'budgets':{'total_ms':1000,'output_tokens':1000,'thinking_time_ms':None}}
        self.planpath=self.root/'plan.json';e.write(self.planpath,self.plan)
        self.workspace=self.root/'public'
        def exporter(task,scale,path):
            path.mkdir(parents=True)
            (path/'PROMPT.md').write_text('Public task '+task)
            (path/'starter.py').write_text('print("starter")\n')
        e.prepare(self.planpath,self.workspace,exporter=exporter)
        self.answer=self.root/'answer.py';self.answer.write_text('print("my own pass claim")\n')
        self.attempt='R3-direct-r01'

    def tearDown(self):
        self.patch.stop()
        for p in self.root.rglob('*'):
            if p.is_dir(): p.chmod(0o755)
        self.tmp.cleanup()

    def test_prepare_shared_tasks_and_private_seeds(self):
        public=e.load(self.workspace/'experiment.json')
        self.assertEqual(public['attempts'],12)
        self.assertEqual(len(list((self.workspace/'tasks').iterdir())),2)
        self.assertEqual(len(list((self.workspace/'answers').iterdir())),12)
        self.assertNotIn('seeds',public)
        record=e.load(self.root/'reports'/'experiments'/'demo'/'organizer.json')
        self.assertEqual(len(record['seeds']['R3']),2)
        self.assertEqual(e.inspect(self.workspace)['counts']['missing'],12)

    def prepare_extra(self,plan):
        planpath=self.root/(plan['id']+'.json');e.write(planpath,plan)
        workspace=self.root/plan['id']
        def exporter(task,scale,path):
            path.mkdir(parents=True)
            (path/'PROMPT.md').write_text('Public task '+task)
            (path/'starter.py').write_text('print("starter")\n')
        e.prepare(planpath,workspace,exporter=exporter)
        return workspace,e.load(self.root/'reports/experiments'/plan['id']/'organizer.json')

    def test_changed_public_controls_block_start_submit_and_grade(self):
        e.submit(self.workspace,self.attempt,self.answer)
        targets=['README.md','experiment.json','assignments.json','answers/'+self.attempt+'/README.md']
        for name in targets:
            with self.subTest(name=name):
                path=self.workspace/name;original=path.read_bytes()
                if name=='experiment.json':
                    value=e.load(path);value['prompt_variants'][0]['text']='different assignment';e.write(path,value)
                elif name=='assignments.json':
                    value=e.load(path);value[0]['prompt']='different assignment';e.write(path,value)
                else:path.write_text('Replaced experiment instructions')
                state=e.inspect(self.workspace)
                self.assertFalse(state['control_integrity']['ok'])
                self.assertFalse(state['control_integrity']['files'][name])
                self.assertFalse(state['integrity_ok'])
                with self.assertRaisesRegex(ValueError,'controls'):e.start(self.workspace,'R3-direct-r02')
                with self.assertRaisesRegex(ValueError,'controls'):e.submit(self.workspace,'R3-direct-r02',self.answer)
                with self.assertRaisesRegex(ValueError,'controls'):e.grade(self.workspace,self.attempt)
                path.write_bytes(original)
        self.assertTrue(e.inspect(self.workspace)['integrity_ok'])

    def test_old_unfrozen_experiment_cannot_be_formally_graded(self):
        e.submit(self.workspace,self.attempt,self.answer)
        path=self.root/'reports/experiments/demo/organizer.json';record=e.load(path)
        del record['control_hashes'];e.write(path,record)
        state=e.inspect(self.workspace)
        self.assertEqual(state['control_integrity']['status'],'not_frozen')
        self.assertFalse(state['integrity_ok'])
        with self.assertRaisesRegex(ValueError,'not frozen'):e.grade(self.workspace,self.attempt)

    def test_same_cohort_reuses_private_cases_without_leaking_seeds(self):
        plan={**self.plan,'id':'model-a','cohort_id':'shared-study'}
        first,a=self.prepare_extra(plan)
        second,b=self.prepare_extra({**plan,'id':'model-b'})
        self.assertEqual(a['seeds'],b['seeds'])
        self.assertEqual(a['comparison_id'],b['comparison_id'])
        self.assertNotEqual(a['control_hashes']['experiment.json'],b['control_hashes']['experiment.json'])
        public=e.load(second/'experiment.json')
        self.assertEqual(public['cohort_id'],'shared-study')
        self.assertEqual(public['comparison_id'],b['comparison_id'])
        self.assertNotIn('seeds',public)
        serialized='\n'.join((second/name).read_text() for name in b['control_hashes'])
        for rounds in b['seeds'].values():
            for seed in rounds.values():self.assertNotIn(str(seed),serialized)
        cohort=self.root/'reports/experiments/cohorts/shared-study.json'
        self.assertEqual(e.load(cohort)['seeds'],a['seeds'])
        self.assertFalse(cohort.with_suffix('.lock').exists())

    def test_cohort_rejects_changed_design_and_preserves_original_case_set(self):
        plan={**self.plan,'id':'cohort-original','cohort_id':'shared-study'}
        self.prepare_extra(plan)
        path=self.root/'reports/experiments/cohorts/shared-study.json';original=path.read_bytes()
        changes=[{'rounds':3},{'scale':'full'},{'tasks':['R3']},{'budgets':{'total_ms':2000}},
                 {'prompt_variants':[{'id':'different','text':'another prompt'}]},
                 {'efficiency_policy':{'profile':'elapsed_only','budgets':{}}}]
        for index,change in enumerate(changes):
            with self.subTest(change=change):
                with self.assertRaisesRegex(ValueError,'cohort design'):
                    self.prepare_extra({**plan,'id':f'mismatch-{index}',**change})
                self.assertEqual(path.read_bytes(),original)

    def test_cohort_does_not_steal_existing_lock_and_source_revision_is_frozen(self):
        folder=self.root/'reports/experiments/cohorts';folder.mkdir(parents=True,exist_ok=True)
        lock=folder/'busy.lock';lock.write_text('another prepare owns this lock')
        with self.assertRaisesRegex(ValueError,'locked'):
            self.prepare_extra({**self.plan,'id':'busy-experiment','cohort_id':'busy'})
        self.assertEqual(lock.read_text(),'another prepare owns this lock')
        source=self.root/'reasoning/extreme.py';source.parent.mkdir();source.write_text('revision_one = True\n')
        workspace,record=self.prepare_extra({**self.plan,'id':'source-a','cohort_id':'source-study'})
        self.assertTrue(e.inspect(workspace)['generator_integrity'])
        source.write_text('revision_two = True\n')
        self.assertFalse(e.inspect(workspace)['generator_integrity'])
        with self.assertRaisesRegex(ValueError,'generator sources'):e.start(workspace,'R3-direct-r01')
        with self.assertRaisesRegex(ValueError,'cohort design'):
            self.prepare_extra({**self.plan,'id':'source-b','cohort_id':'source-study'})

    def test_independent_experiments_get_different_comparison_ids(self):
        _,a=self.prepare_extra({**self.plan,'id':'independent-a'})
        _,b=self.prepare_extra({**self.plan,'id':'independent-b'})
        self.assertNotEqual(a['seeds'],b['seeds'])
        self.assertNotEqual(a['comparison_id'],b['comparison_id'])

    def test_efficiency_policy_is_frozen_in_public_and_private_plan(self):
        plan={**self.plan,'id':'frozen','efficiency_policy':{'profile':'elapsed_only','budgets':{'total_ms':120000}}}
        path=self.root/'frozen-plan.json';e.write(path,plan)
        def exporter(task,scale,destination):
            destination.mkdir(parents=True);(destination/'PROMPT.md').write_text('public')
        workspace=self.root/'frozen-public';e.prepare(path,workspace,exporter=exporter)
        public=e.load(workspace/'experiment.json')
        private=e.load(self.root/'reports/experiments/frozen/organizer.json')
        self.assertEqual(public['efficiency_policy'],private['efficiency_policy'])
        self.assertEqual(e.load(workspace/'efficiency-budgets.json')['total_ms'],120000)
        self.assertNotIn('seeds',public)
        self.assertTrue(e.inspect(workspace)['control_integrity']['files']['efficiency-budgets.json'])
        budgets=e.load(workspace/'efficiency-budgets.json');budgets['total_ms']=1
        e.write(workspace/'efficiency-budgets.json',budgets)
        self.assertFalse(e.inspect(workspace)['control_integrity']['ok'])
        with self.assertRaisesRegex(ValueError,'controls'):e.start(workspace,self.attempt)

    def test_atomic_submit_and_overwrite_refusal(self):
        sealed=e.submit(self.workspace,self.attempt,self.answer)
        self.assertEqual(sealed['status'],'sealed')
        self.assertEqual(e.inspect(self.workspace)['counts'],{'missing':11,'sealed':1,'tampered':0})
        with self.assertRaises(ValueError): e.submit(self.workspace,self.attempt,self.answer)
        self.assertFalse((self.workspace/'answers'/self.attempt/'.submit.lock').exists())

    def test_start_creates_editable_copy_without_changing_shared_input(self):
        info=e.start(self.workspace,self.attempt)
        work=Path(info['work'])
        (work/'starter.py').write_text('print("edited")\n')
        self.assertTrue(e.inspect(self.workspace)['task_input_integrity']['R3'])
        self.assertTrue(e.inspect(self.workspace)['control_integrity']['ok'])
        self.assertFalse(info['timing_verified'])
        with self.assertRaises(ValueError): e.start(self.workspace,self.attempt)

    def test_submission_destination_symlink_is_refused(self):
        target=self.workspace/'answers'/self.attempt
        shutil.rmtree(target)
        external=self.root/'outside';external.mkdir()
        target.symlink_to(external,target_is_directory=True)
        with self.assertRaises(ValueError): e.submit(self.workspace,self.attempt,self.answer)
        with self.assertRaises(ValueError): e.start(self.workspace,self.attempt)
        self.assertEqual(e.inspect(self.workspace)['attempts'][0]['status'],'tampered')
        self.assertEqual(list(external.iterdir()),[])

    def test_file_tamper_detected_and_grade_refused(self):
        e.submit(self.workspace,self.attempt,self.answer)
        file=self.workspace/'answers'/self.attempt/'sealed'/'payload'/'answer.py'
        file.chmod(0o644);file.write_text('modified')
        self.assertEqual(e.inspect(self.workspace)['counts']['tampered'],1)
        with self.assertRaises(ValueError): e.grade(self.workspace,self.attempt)

    def test_manifest_rewrite_does_not_hide_tamper(self):
        e.submit(self.workspace,self.attempt,self.answer)
        sealed=self.workspace/'answers'/self.attempt/'sealed'
        manifest=sealed/'manifest.json';manifest.chmod(0o644)
        value=e.load(manifest);value['source']='forged source';e.write(manifest,value)
        self.assertEqual(e.inspect(self.workspace)['counts']['tampered'],1)

    def test_missing_and_shared_input_tamper(self):
        with self.assertRaises(ValueError): e.grade(self.workspace,self.attempt)
        file=self.workspace/'tasks'/'R3'/'PROMPT.md';file.chmod(0o644);file.write_text('changed')
        self.assertFalse(e.inspect(self.workspace)['task_input_integrity']['R3'])

    def test_symlink_and_entrypoint_escape_refused(self):
        solution=self.root/'solution';solution.mkdir()
        (solution/'alias.py').symlink_to(self.answer)
        with self.assertRaises(ValueError): e.submit(self.workspace,self.attempt,solution,entrypoint='alias.py')
        (solution/'alias.py').unlink();(solution/'policy.py').write_text('pass')
        with self.assertRaises(ValueError): e.submit(self.workspace,self.attempt,solution,entrypoint='../answer.py')
        self.assertEqual(e.inspect(self.workspace)['counts']['sealed'],0)
        e.submit(self.workspace,self.attempt,solution,entrypoint='policy.py')
        self.assertEqual(e.inspect(self.workspace)['counts']['sealed'],1)

    def test_source_label_never_promotes_metrics(self):
        metrics=self.root/'metrics.json';e.write(metrics,{'source':'API','total_ms':40,'output_tokens':5})
        e.submit(self.workspace,self.attempt,self.answer,metrics)
        met=e.load(self.workspace/'answers'/self.attempt/'sealed'/'metrics.json')
        self.assertFalse(met['efficiency_eligible'])
        self.assertEqual(met['trust'],'unverified')
        self.assertIsNone(met['thinking_time_ms'])
        e.write(metrics,{'output_tokens':True})
        with self.assertRaises(ValueError): e.metrics_record(metrics)

    def test_sealing_retains_simulation_marker_and_cumulative_retry_metadata(self):
        metrics=self.root/'metrics.json'
        original={'source':'host','simulated':True,'total_ms':1000,'ttft_ms':5,
                  'logical_total_ms':100000,'logical_ttft_ms':30,
                  'output_tokens':100,'logical_output_tokens':10000,
                  'reasoning_tokens':80,'logical_reasoning_tokens':8000,'logical_final':True,
                  'measurement_source':'host_api_stream','latency_source':'monotonic_host_clock',
                  'measurement_scope':'logical_run',
                  'reasoning_content':'private text must not enter the metric schema',
                  'api_key':'synthetic-secret-must-not-be-copied'}
        e.write(metrics,original)
        e.submit(self.workspace,self.attempt,self.answer,metrics)
        sealed=e.load(self.workspace/'answers'/self.attempt/'sealed'/'metrics.json')
        for key in ('simulated',*e.LOGICAL_METRICS,*e.METRIC_LABELS,'logical_final'):
            self.assertEqual(sealed[key],original[key])
        self.assertEqual(sealed['trust'],'unverified')
        self.assertFalse(sealed['efficiency_eligible'])
        self.assertNotIn('reasoning_content',sealed)
        self.assertNotIn('api_key',sealed)
        self.assertNotIn(original['api_key'],json.dumps(sealed))
        self.assertEqual(eff.score_efficiency(100,True,sealed,trusted=True)['status'],
                         'simulated_metrics_not_official')

    def test_sealed_retry_totals_are_used_and_unknown_totals_do_not_fall_back(self):
        metrics=self.root/'metrics.json'
        value={'source':'API','simulated':False,'total_ms':1000,'ttft_ms':5,
               'logical_total_ms':120000,'logical_ttft_ms':30,
               'output_tokens':100,'logical_output_tokens':20000,
               'reasoning_tokens':70,'logical_reasoning_tokens':12000,'logical_final':True}
        e.write(metrics,value)
        e.submit(self.workspace,self.attempt,self.answer,metrics)
        sealed=e.load(self.workspace/'answers'/self.attempt/'sealed'/'metrics.json')
        self.assertEqual(eff.score_efficiency(100,True,sealed)['status'],
                         'host_or_provider_evidence_not_verified')
        scored=eff.score_efficiency(100,True,sealed,trusted=True)
        self.assertEqual(scored['observed']['total_ms'],120000)
        self.assertEqual(scored['observed']['output_tokens'],20000)
        self.assertLess(scored['adjusted_quality'],100)
        value['logical_output_tokens']=None
        e.write(metrics,value)
        projected=e.metrics_record(metrics)
        self.assertIn('logical_output_tokens',projected)
        self.assertIsNone(projected['logical_output_tokens'])
        self.assertEqual(eff.score_efficiency(100,True,projected,trusted=True,profile='time_tokens')['status'],
                         'output_usage_unavailable')

    def test_optional_metric_metadata_is_strict_and_legacy_template_is_compatible(self):
        metrics=self.root/'metrics.json'
        for value in ({'simulated':'false'}, {'logical_final':1}, {'logical_total_ms':True},
                      {'logical_output_tokens':1.5}, {'logical_reasoning_tokens':-1},
                      {'measurement_source':{}}, {'latency_source':'not a machine label'},
                      {'measurement_scope':'x'*129}, {'logical_total_ms':2,'logical_ttft_ms':3},
                      {'logical_output_tokens':2,'output_tokens':3}):
            with self.subTest(value=value):
                e.write(metrics,value)
                with self.assertRaises(ValueError): e.metrics_record(metrics)
        e.write(metrics,{key:None for key in e.METRICS})
        projected=e.metrics_record(metrics)
        self.assertTrue(all(projected[key] is None for key in e.METRICS))
        self.assertNotIn('logical_total_ms',projected)
        self.assertNotIn('simulated',projected)
        self.assertFalse(projected['efficiency_eligible'])

    def test_grade_calls_judge_and_frontend_stays_pending(self):
        e.submit(self.workspace,'F1-direct-r01',self.answer)
        commands=[]
        def runner(command,timeout):
            commands.append(command)
            output=Path(command[command.index('--output')+1])
            seed=int(command[command.index('--seed')+1])
            task=command[command.index('--task')+1]
            submission=Path(command[command.index('--submission')+1])
            self.assertNotIn('/sealed/',str(submission))
            self.assertEqual(submission.read_text(),self.answer.read_text())
            e.write(output/(task+'.json'),{'task_id':task,'seed':seed,'audit_passed':True,
                    'candidate_result':{'valid':False,'raw_score':3,'note':'self-reported pass ignored'}})
            return {'exit_code':0,'command':command}
        result=e.grade(self.workspace,'F1-direct-r01',runner=runner)
        self.assertFalse(result['candidate_result']['valid'])
        self.assertEqual(result['frontend_visual_review'],'pending')
        self.assertFalse(result['efficiency_eligible'])
        again=e.grade(self.workspace,'F1-direct-r01',runner=runner)
        self.assertNotEqual(result['grade'],again['grade'])
        self.assertEqual(len(commands),2)

    def test_valid_frontend_semantic_score_reaches_quality_without_visual_promotion(self):
        e.submit(self.workspace,'F1-direct-r01',self.answer)
        def runner(command,timeout):
            output=Path(command[command.index('--output')+1])
            seed=int(command[command.index('--seed')+1])
            e.write(output/'F1.json',{'task_id':'F1','seed':seed,'audit_passed':True,
                    'candidate_result':{'valid':True,'semantic_score':100,'quality_score':None,
                                        'human_visual_score':None}})
            return {'exit_code':0,'command':command}
        result=e.grade(self.workspace,'F1-direct-r01',runner=runner)
        grade=e.load(result['grade'])
        quality=e.load(grade['quality_artifact'])
        self.assertEqual(quality['raw_score'],100)
        self.assertEqual(quality['scope'],'semantic_only')
        self.assertEqual(quality['frontend_visual_review'],'pending')
        self.assertEqual(quality['complete_frontend_status'],'pending')
        self.assertIsNone(quality['complete_frontend_score'])
        self.assertFalse(grade['efficiency_eligible'])
        scored=eff.score_efficiency(quality['raw_score'],quality['valid'],{'total_ms':1000},trusted=True)
        self.assertEqual(scored['status'],'scored')
        self.assertEqual(scored['adjusted_quality'],100)
        scheduled=next(row for row in grade['scheduled_attempts'] if row['attempt_id']=='F1-direct-r01')
        self.assertEqual(scheduled['quality_score'],100)

    def test_baseline_only_result_is_refused(self):
        e.submit(self.workspace,self.attempt,self.answer)
        def runner(command,timeout):
            output=Path(command[command.index('--output')+1]);seed=int(command[command.index('--seed')+1])
            e.write(output/'R3.json',{'task_id':'R3','seed':seed,'baseline_result':{'valid':True}})
            return {'exit_code':0}
        with self.assertRaises(ValueError): e.grade(self.workspace,self.attempt,runner=runner)


if __name__=='__main__': unittest.main()
