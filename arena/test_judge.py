import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from arena import judge,rules


def code_report(task='C1',fail_stage=True):
    names=rules.CODE_SILVER[task]
    checks=[{'name':name,'passed':True} for name in names]
    checks.append({'name':'stage_v2_capability' if fail_stage else 'stage_v2_pair_0','passed':not fail_stage})
    return {'audit_passed':True,'candidate_result':{'valid':not fail_stage,'checks':checks}}


class JudgeTests(unittest.TestCase):
    def test_low_scope_ignores_unselected_stage_failure(self):
        report=code_report()
        for tier in ('bronze','silver'):
            result=judge.score_report(report,rules.draw_spec('C1',tier,1)['private'])
            self.assertTrue(result['valid']);self.assertEqual(result['raw_score'],100)
        result=judge.score_report(report,rules.draw_spec('C1','gold',1)['private'])
        self.assertFalse(result['valid']);self.assertEqual(result['raw_score'],0)

    def test_partial_quality_and_foundation_failure_differ(self):
        spec=rules.draw_spec('C4','silver',1)['private'];report=code_report('C4')
        report['candidate_result']['checks'][1]['passed']=False
        result=judge.score_report(report,spec)
        self.assertTrue(result['valid']);self.assertFalse(result['completed']);self.assertEqual(result['raw_score'],50)
        report['candidate_result']['checks'][0]['passed']=False
        self.assertEqual(judge.score_report(report,spec)['raw_score'],0)

    def test_frontend_only_selected_semantics_count(self):
        names=rules.FRONT_SILVER['F1'];checks=[{'name':x,'passed':True} for x in names]+[{'name':'outside silver','passed':False}]
        report={'audit_passed':True,'candidate_result':{'valid':False,'checks':checks}}
        result=judge.score_report(report,rules.draw_spec('F1','silver',3)['private'])
        self.assertTrue(result['valid']);self.assertEqual(len(result['selected_checks']),3)
        self.assertEqual(result['score_scope'],'semantic_only')

    def test_reasoning_scope_recomputes_only_selected_episodes_without_threshold(self):
        report={'audit_passed':True,'candidate_result':{'valid':False,'loss_scale':50,
             'episodes_detail':[{'valid':True,'loss':1000},{'valid':False,'loss':250}]}}
        small=judge.score_report(report,rules.draw_spec('R1','bronze',1)['private'])
        self.assertTrue(small['valid']);self.assertLess(small['raw_score'],5)
        large=judge.score_report(report,rules.draw_spec('R1','silver',1)['private'])
        self.assertFalse(large['valid']);self.assertEqual(large['raw_score'],0)

    def test_missing_selected_check_and_absent_stage_are_failures(self):
        report=code_report();report['candidate_result']['checks']=report['candidate_result']['checks'][1:]
        result=judge.score_report(report,rules.draw_spec('C1','bronze',1)['private'])
        self.assertFalse(result['valid']);self.assertEqual(result['raw_score'],0)
        report=code_report(fail_stage=False);report['candidate_result']['checks'].pop()
        result=judge.score_report(report,rules.draw_spec('C1','gold',1)['private'])
        self.assertFalse(result['valid']);self.assertEqual(result['raw_score'],0)

    def test_bad_judge_evidence_is_unknown_not_candidate_zero(self):
        with self.assertRaises(ValueError):judge.score_report({'audit_passed':False},rules.draw_spec('C1','bronze',1)['private'])

    def test_same_draw_two_candidates_get_same_instance_and_unverified_efficiency(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);submission=root/'source';submission.mkdir();(submission/'app.py').write_text('pass')
            spec=rules.draw_spec('C1','bronze',41)['private'];observed=[]
            def runner(command,directory,timeout,cancel_event,progress,index,count):
                seed=int(command[command.index('--seed')+1]);observed.append(seed)
                report=code_report();report.update(task_id='C1',seed=seed,scale='smoke')
                target=Path(command[command.index('--output')+1]);target.mkdir()
                (target/'C1.json').write_text(json.dumps(report))
                return {'status':'completed','exit_code':0,'elapsed_seconds':.01}
            with mock.patch.object(judge,'_run',runner):
                a=judge.grade_match(spec,submission,root/'a',metrics={'source':'API','total_ms':1})
                b=judge.grade_match(spec,submission,root/'b')
            self.assertEqual(observed,[spec['case_seeds'][0]]*2)
            self.assertTrue(a['completed']);self.assertEqual(a['raw_score'],b['raw_score'])
            self.assertIsNone(a['efficiency_score']);self.assertFalse(a['efficiency_eligible'])
            self.assertNotIn(str(spec['case_seeds'][0]),json.dumps(a))

    def test_legal_partial_quality_survives_efficiency_scoring(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source';source.mkdir();(source/'module.py').write_text('pass')
            spec=rules.draw_spec('C4','silver',8)['private']
            def runner(command,directory,timeout,cancel_event,progress,index,count):
                seed=int(command[command.index('--seed')+1]);report=code_report('C4')
                report['candidate_result']['checks'][1]['passed']=False
                report.update(task_id='C4',seed=seed,scale='smoke')
                target=Path(command[command.index('--output')+1]);target.mkdir()
                (target/'C4.json').write_text(json.dumps(report))
                return {'status':'completed','exit_code':0,'elapsed_seconds':.01}
            with mock.patch.object(judge,'_run',runner):
                result=judge.grade_match(spec,source,root/'graded',metrics={'total_ms':1000},verified_metrics=True)
            self.assertTrue(result['valid']);self.assertTrue(result['legal'])
            self.assertFalse(result['completed']);self.assertEqual(result['status'],'partial')
            self.assertEqual(result['raw_score'],50);self.assertEqual(result['efficiency_score'],50)

    def test_cancellation_stops_current_child_session(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);script=root/'sleep.py';childfile=root/'child.pid'
            script.write_text('import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"],start_new_session=True)\nPath('+repr(str(childfile))+').write_text(str(p.pid))\ntime.sleep(60)\n')
            cancel=threading.Event();timer=threading.Timer(.3,cancel.set);timer.start()
            try:result=judge._run([sys.executable,str(script)],root,10,cancel)
            finally:timer.cancel()
            self.assertEqual(result['status'],'cancelled')
            if childfile.exists():
                child=int(childfile.read_text());state=subprocess.run(['ps','-o','stat=','-p',str(child)],capture_output=True,text=True).stdout.strip()
                self.assertTrue(not state or state.startswith('Z'),state)


if __name__=='__main__':unittest.main()
