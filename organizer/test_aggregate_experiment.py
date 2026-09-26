from __future__ import annotations
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

BASE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('aggregate_experiment',BASE/'aggregate_experiment.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
espec=importlib.util.spec_from_file_location('aggregate_efficiency',BASE/'efficiency.py')
eff=importlib.util.module_from_spec(espec);espec.loader.exec_module(eff)
e=a.experiment


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patch=mock.patch.object(e,'ROOT',self.root);self.patch.start()
        self.plan={'id':'study','tasks':['R3'],'scale':'smoke','rounds':3,
                   'prompt_variants':[{'id':'a','text':'first'},{'id':'b','text':'second'}],
                   'budgets':{'total_ms':60000}}
        self.plan_path=self.root/'plan.json';e.write(self.plan_path,self.plan)
        self.workspace=self.root/'workspace'
        def exporter(task,scale,destination):
            destination.mkdir(parents=True);(destination/'PROMPT.md').write_text('public')
        e.prepare(self.plan_path,self.workspace,exporter=exporter)
        self.source=self.root/'policy.py';self.source.write_text('pass\n')

    def tearDown(self):
        self.patch.stop()
        for p in self.root.rglob('*'):
            if p.is_dir():p.chmod(0o755)
        self.temp.cleanup()

    def seal(self,aid,metrics=None):
        path=None
        if metrics is not None:
            path=self.root/'metrics.json';e.write(path,metrics)
        return e.submit(self.workspace,aid,self.source,path)

    def grade(self,aid,score,valid=True):
        def runner(command,timeout):
            output=Path(command[command.index('--output')+1]);seed=int(command[command.index('--seed')+1])
            e.write(output/'R3.json',{'task_id':'R3','seed':seed,'audit_passed':True,
                                     'candidate_result':{'valid':valid,'raw_score':score}})
            return {'exit_code':0,'command':command}
        result=e.grade(self.workspace,aid,runner=runner)
        return Path(result['grade'])

    def efficiency(self,grade_path,budgets=None,*,trusted=True):
        quality_path=grade_path.parent/'quality.json';quality=e.load(quality_path)
        report=eff.score_efficiency(quality['raw_score'],quality['valid'],
              {'total_ms':120000,'ttft_ms':100,'output_tokens':100},budgets,trusted=trusted)
        report['quality_artifact_sha256']=e.sha(quality_path)
        e.write(grade_path.parent/'efficiency.json',report)
        return report

    def test_missing_attempts_count_as_zero_not_dropped(self):
        result=a.aggregate(self.workspace,'model-a')
        self.assertEqual(len(result['attempts']),6)
        self.assertEqual(result['counts']['missing'],6)
        self.assertEqual(result['tasks'][0]['quality_score'],0)
        self.assertEqual(result['tasks'][0]['efficiency_score'],0)
        self.assertEqual(result['performance']['total_ms']['missing'],6)

    def test_efficiency_must_match_preregistered_policy(self):
        plan={**self.plan,'id':'frozen-study','efficiency_policy':{'profile':'elapsed_only','budgets':{'total_ms':60000}}}
        e.write(self.plan_path,plan)
        def exporter(task,scale,destination):
            destination.mkdir(parents=True);(destination/'PROMPT.md').write_text('public')
        self.workspace=self.root/'frozen-workspace'
        e.prepare(self.plan_path,self.workspace,exporter=exporter)
        self.seal('R3-a-r01');path=self.grade('R3-a-r01',80)
        self.efficiency(path, {'total_ms':120000})
        result=a.aggregate(self.workspace)
        self.assertIsNone(result['attempts'][0]['efficiency_score'])
        self.assertIn('preregistered',result['attempts'][0]['efficiency']['reason'])

    def test_missing_zero_enters_efficiency_median_without_creating_a_policy(self):
        self.seal('R3-a-r01');path=self.grade('R3-a-r01',80)
        profile=self.efficiency(path)
        result=a.aggregate(self.workspace)
        self.assertEqual(result['variants'][0]['efficiency_rounds'],[68,0,0])
        self.assertEqual(result['variants'][0]['efficiency_median'],0)
        self.assertEqual(result['tasks'][0]['efficiency_score'],0)
        self.assertEqual(result['tasks'][0]['score_profile_id'],profile['score_profile_id'])
        self.assertEqual(result['leaderboard_records'][0]['task_id'],'R3')

    def test_pending_null_propagates(self):
        self.seal('R3-a-r01')
        result=a.aggregate(self.workspace)
        self.assertEqual(result['counts']['pending'],1)
        self.assertIsNone(result['variants'][0]['quality_median'])
        self.assertIsNone(result['tasks'][0]['quality_score'])
        self.assertIsNone(result['leaderboard_records'][0]['raw_score'])
        self.assertIsNone(result['tasks'][0]['efficiency_score'])

    def test_first_invalid_grade_cannot_be_replaced_by_high_score(self):
        self.seal('R3-a-r01')
        first=self.grade('R3-a-r01',0,False)
        later=self.grade('R3-a-r01',99,True)
        result=a.aggregate(self.workspace)
        row=result['attempts'][0]
        self.assertEqual(row['quality_score'],0)
        self.assertEqual(row['status'],'invalid')
        self.assertEqual(row['efficiency_score'],0)
        self.assertIsNone(row['efficiency']['score_profile_id'])
        self.assertEqual(row['selected_grade'],str(first))
        self.assertEqual(row['ignored_later_completed_grades'],[str(later)])

    def test_runner_error_is_pending_but_later_completed_grade_counts(self):
        self.seal('R3-a-r01')
        failed=e.private_path('study')/'results'/'R3-a-r01'/'000-error'/'grade.json'
        e.write(failed,{'status':'runner_error','attempt_id':'R3-a-r01'})
        self.assertIsNone(a.aggregate(self.workspace)['attempts'][0]['quality_score'])
        good=self.grade('R3-a-r01',70)
        result=a.aggregate(self.workspace)
        self.assertEqual(result['attempts'][0]['quality_score'],70)
        self.assertEqual(result['attempts'][0]['selected_grade'],str(good))

    def test_variant_medians_are_equally_weighted(self):
        for variant,values in [('a',[0,0,100]),('b',[100,100,100])]:
            for i,score in enumerate(values,1):
                aid=f'R3-{variant}-r{i:02d}';self.seal(aid);self.grade(aid,score)
        result=a.aggregate(self.workspace)
        self.assertEqual([r['quality_median'] for r in result['variants']],[0,100])
        self.assertEqual(result['tasks'][0]['quality_score'],50)
        self.assertEqual(result['counts']['graded'],6)

    def test_mixed_budget_profiles_refused(self):
        for i,budget in enumerate([{'total_ms':60000},{'total_ms':30000}],1):
            aid=f'R3-a-r{i:02d}';self.seal(aid)
            path=self.grade(aid,80);self.efficiency(path,budget)
        with self.assertRaisesRegex(ValueError,'mixed efficiency profiles/budgets'):
            a.aggregate(self.workspace)

    def test_logical_totals_and_explicit_null_take_precedence(self):
        self.seal('R3-a-r01',{'source':'API','total_ms':10,'logical_total_ms':100,
                    'ttft_ms':5,'logical_ttft_ms':20,'output_tokens':5,'logical_output_tokens':50,
                    'reasoning_tokens':2,'logical_reasoning_tokens':None})
        self.grade('R3-a-r01',60)
        result=a.aggregate(self.workspace)
        metrics=result['performance']
        self.assertEqual(metrics['total_ms']['mean'],100)
        self.assertEqual(metrics['total_ms']['max'],100)
        self.assertEqual(metrics['output_tokens']['p50'],50)
        self.assertEqual(metrics['reasoning_tokens']['missing'],6)
        self.assertEqual(metrics['trust'],'unverified')
        self.assertFalse(metrics['used_for_scoring'])
        self.assertIsNone(result['attempts'][0]['efficiency_score'])

    def test_simulated_metrics_never_count_as_real_efficiency(self):
        self.seal('R3-a-r01',{'total_ms':20,'simulated':True})
        path=self.grade('R3-a-r01',80);self.efficiency(path)
        result=a.aggregate(self.workspace)
        self.assertIsNone(result['attempts'][0]['efficiency_score'])
        self.assertIn('simulated',result['attempts'][0]['efficiency']['reason'])

    def test_quality_hash_mismatch_leaves_efficiency_pending(self):
        self.seal('R3-a-r01');path=self.grade('R3-a-r01',80)
        report=self.efficiency(path);report['quality_artifact_sha256']='0'*64
        e.write(path.parent/'efficiency.json',report)
        result=a.aggregate(self.workspace)
        self.assertIsNone(result['attempts'][0]['efficiency_score'])
        self.assertEqual(result['attempts'][0]['quality_score'],80)

    def test_verified_consistent_efficiency_aggregates_separately(self):
        for variant in ('a','b'):
            for round_id in range(1,4):
                aid=f'R3-{variant}-r{round_id:02d}';self.seal(aid)
                path=self.grade(aid,80);self.efficiency(path)
        result=a.aggregate(self.workspace)
        self.assertEqual(result['tasks'][0]['quality_score'],80)
        self.assertEqual(result['tasks'][0]['efficiency_score'],68)
        self.assertIsNotNone(result['tasks'][0]['score_profile_id'])
        self.assertEqual(result['performance']['trust'],'unverified')

    def test_frontend_semantic_score_is_not_a_complete_ui_ranking(self):
        plan=dict(self.plan,id='frontend',tasks=['F1'],rounds=1,
                  prompt_variants=[{'id':'direct','text':'read and build'}])
        planpath=self.root/'front-plan.json';e.write(planpath,plan)
        workspace=self.root/'front-workspace'
        def exporter(task,scale,path):
            path.mkdir(parents=True);(path/'PROMPT.md').write_text('frontend')
        e.prepare(planpath,workspace,exporter=exporter)
        e.submit(workspace,'F1-direct-r01',self.source)
        def runner(command,timeout):
            output=Path(command[command.index('--output')+1]);seed=int(command[command.index('--seed')+1])
            e.write(output/'F1.json',{'task_id':'F1','seed':seed,'audit_passed':True,
                    'candidate_result':{'valid':True,'raw_score':None,'semantic_score':64}})
            return {'exit_code':0}
        e.grade(workspace,'F1-direct-r01',runner=runner)
        result=a.aggregate(workspace)
        self.assertEqual(result['tasks'][0]['quality_score'],64)
        self.assertEqual(result['tasks'][0]['score_scope'],'semantic_only')
        self.assertIsNone(result['tasks'][0]['complete_frontend_score'])
        self.assertFalse(result['leaderboard_records'][0]['final_ui_leaderboard_eligible'])

    def test_tampered_answers_zero_even_with_prior_grade(self):
        self.seal('R3-a-r01');self.grade('R3-a-r01',80)
        file=self.workspace/'answers'/'R3-a-r01'/'sealed'/'payload'/'policy.py'
        file.chmod(0o644);file.write_text('tampered')
        result=a.aggregate(self.workspace)
        self.assertEqual(result['attempts'][0]['status'],'tampered')
        self.assertEqual(result['attempts'][0]['quality_score'],0)
        self.assertEqual(result['attempts'][0]['efficiency_score'],0)
        self.assertIsNone(result['attempts'][0]['selected_grade'])


if __name__=='__main__':unittest.main()
