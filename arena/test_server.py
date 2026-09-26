import hashlib
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request
import zipfile

from arena import rules,server,storage

ROOT=Path(__file__).resolve().parents[1]


def exporter(task,scale,destination):
    destination.mkdir()
    (destination/'PROMPT.md').write_text('Public contract only')
    (destination/'policy.py').write_text('print("demo")\n')


def grade_result(score=75,valid=True,completed=True,frontend=False):
    return {'valid':valid,'legal':valid,'completed':completed,'raw_score':score,
            'codex_review_required':frontend,'review_scope':'visual' if frontend else 'machine',
            'score_scope':'semantic_only' if frontend else 'machine_contract',
            'cases':[{'index':1,'valid':valid,'legal':valid,'completed':completed,'raw_score':score,
                      'summary':'checked','status':'passed' if completed else 'partial','failures':[]}],
            'selected_checks':['actual_check']}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.store=storage.ArenaStore(self.root/'arena',draw_factory=lambda task,tier:rules.draw_spec(task,tier,73458321),exporter=exporter)
        self.app=server.ArenaApp(self.store,grader=lambda *a,**k:grade_result())
        with mock.patch.object(socket,'getfqdn',side_effect=AssertionError('reverse DNS is forbidden')):
            self.http=server.make_server(self.app)
        self.thread=threading.Thread(target=self.http.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.http.server_port)
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.source=self.root/'answer';self.source.mkdir();(self.source/'policy.py').write_text('pass\n')
    def tearDown(self):
        self.app.close();self.http.shutdown();self.http.server_close();self.thread.join(2)
        for path in self.root.rglob('*'):
            if path.is_dir():path.chmod(0o755)
        self.temp.cleanup()
    def request(self,path,body=None,headers=None):
        data=None if body is None else json.dumps(body).encode()
        defaults={} if data is None else {'Content-Type':'application/json','X-Arena-CSRF':self.app.csrf}
        defaults.update(headers or {})
        request=urllib.request.Request(self.url+path,data=data,headers=defaults)
        try:
            with self.opener.open(request,timeout=6) as response:return response.status,response.read()
        except urllib.error.HTTPError as exc:
            try:return exc.code,exc.read()
            finally:exc.close()
    def json(self,path,body=None,headers=None):
        status,data=self.request(path,body,headers);return status,json.loads(data)
    def draw(self,task='R3'):
        status,match=self.json('/api/draw',{'task_id':task,'tier':'bronze'});self.assertEqual(status,201,match);return match
    def submit(self,match,participant='model-a',**values):
        status,result=self.json('/api/matches/'+match['id']+'/submit',dict(participant=participant,source_path=str(self.source),entrypoint='policy.py',**values))
        self.assertEqual(status,201,result);return result
    def grade(self,match,submission):
        code,job=self.json('/api/matches/'+match['id']+'/grade',{'submission_id':submission['id']});self.assertEqual(code,202,job)
        self.app.threads[job['id']].join(10)
        self.assertFalse(self.app.threads[job['id']].is_alive())
        return self.app.status(match['id'])['job']

    def test_origin_nonce_host_and_no_shell_endpoint(self):
        _,bootstrap=self.json('/api/bootstrap');self.assertEqual(len(bootstrap['tasks']),12);self.assertEqual(len(bootstrap['tiers']),6)
        payload={'task_id':'R3','tier':'bronze'}
        self.assertEqual(self.json('/api/draw',payload,{'X-Arena-CSRF':'wrong'})[0],403)
        self.assertEqual(self.json('/api/draw',payload,{'Origin':'https://outside.example'})[0],403)
        self.assertEqual(self.json('/api/bootstrap',headers={'Host':'outside.example'})[0],403)
        self.assertEqual(self.json('/api/shell',{'command':'touch arbitrary-file'})[0],404)
        self.assertEqual(self.json('/api/import-review',{'trusted':True})[0],404)

    def test_draw_seal_grade_and_no_private_seed_in_responses(self):
        match=self.draw();submission=self.submit(match);job=self.grade(match,submission)
        self.assertEqual(job['status'],'completed')
        code,report=self.json('/api/matches/'+match['id']+'/report');self.assertEqual(code,200)
        row=report['reports'][0];self.assertTrue(row['valid']);self.assertEqual(row['raw_score'],75)
        self.assertEqual(row['relative_score'],100);self.assertFalse(row['efficiency_eligible'])
        record=storage.read(self.store.folder(match['id'])/'private'/'draw.json')
        for endpoint in ('status','report','leaderboard','grading-request'):
            _,body=self.request('/api/matches/'+match['id']+'/'+endpoint)
            for seed in record['private']['case_seeds']:self.assertNotIn(str(seed).encode(),body)
        _,archive=self.request('/api/matches/'+match['id']+'/download')
        self.assertTrue(archive.startswith(b'PK'))

    def test_answer_and_public_bundle_tampering_are_rejected(self):
        match=self.draw();submission=self.submit(match)
        file=self.store.folder(match['id'])/'submissions'/submission['id']/'sealed'/'payload'/'policy.py'
        file.chmod(0o644);file.write_text('changed')
        self.assertEqual(self.json('/api/matches/'+match['id']+'/grade',{'submission_id':submission['id']})[0],400)
        fresh=self.draw();public=self.store.folder(fresh['id'])/'public.zip';public.write_bytes(b'changed')
        self.assertEqual(self.json('/api/matches/'+fresh['id']+'/download')[0],400)

    def test_zip_slip_symlinks_and_duplicate_participants_are_refused(self):
        match=self.draw();archive=self.root/'evil.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('../outside','bad')
        status,_=self.json('/api/matches/'+match['id']+'/submit',{'participant':'zip','source_path':str(archive),'entrypoint':'.'})
        self.assertEqual(status,400);self.assertFalse((self.root/'outside').exists())
        link=self.root/'linked';link.symlink_to(self.source,target_is_directory=True)
        self.assertEqual(self.json('/api/matches/'+match['id']+'/submit',{'participant':'link','source_path':str(link),'entrypoint':'.'})[0],400)
        self.submit(match)
        self.assertEqual(self.json('/api/matches/'+match['id']+'/submit',{'participant':'model-a','source_path':str(self.source),'entrypoint':'policy.py'})[0],400)

    def test_first_official_result_is_frozen_and_all_invalid_has_no_champion(self):
        match=self.draw();submission=self.submit(match)
        self.app.grader=lambda *a,**k:grade_result(0,False,False)
        self.grade(match,submission)
        self.app.grader=lambda *a,**k:grade_result(99,True,True)
        again=self.grade(match,submission);self.assertTrue(again['diagnostic'])
        board=self.store.leaderboard(match['id']);self.assertEqual(board['entries'][0]['raw_score'],0)
        self.assertEqual(board['entries'][0]['relative_score'],0);self.assertIsNone(board['champion']);self.assertTrue(board['all_invalid'])

    def test_partial_counts_completed_cases_and_frontend_semantics_rank(self):
        match=self.draw('F3');submission=self.submit(match)
        self.app.grader=lambda *a,**k:grade_result(50,True,False,True)
        self.grade(match,submission);view=self.app.status(match['id'])['submissions'][0]
        self.assertEqual(view['passed_cases'],0);self.assertFalse(view['completed']);self.assertEqual(view['status'],'review_pending')
        board=self.store.leaderboard(match['id']);self.assertEqual(board['entries'][0]['relative_score'],100)
        self.assertEqual(board['champion_scope'],'semantic_only');self.assertIsNone(board['complete_frontend_champion'])

    def test_unknown_environment_is_retryable_not_candidate_failure(self):
        match=self.draw();submission=self.submit(match)
        self.app.grader=lambda *a,**k:dict(grade_result(None,None,None),status='environment_error')
        self.assertEqual(self.grade(match,submission)['status'],'failed')
        view=self.app.status(match['id'])['submissions'][0];self.assertIsNone(view['valid']);self.assertIsNone(view['raw_score'])
        self.app.grader=lambda *a,**k:grade_result()
        self.assertTrue(self.grade(match,submission)['official_result'])

    def test_cancel_ack_prevents_official_result(self):
        entered=threading.Event()
        def slow(*args,**kwargs):
            entered.set();kwargs['cancel_event'].wait(3);return grade_result()
        self.app.grader=slow;match=self.draw();submission=self.submit(match)
        job=self.app.start_grade(match['id'],submission['id']);self.assertTrue(entered.wait(2))
        self.app.cancel(match['id'],job['id']);self.app.threads[job['id']].join(3)
        self.assertEqual(self.app.status(match['id'])['job']['status'],'cancelled')
        self.assertFalse((self.store.folder(match['id'])/'private'/('official-'+submission['id']+'.json')).exists())

    def test_cancel_and_official_publication_have_one_linearization_point(self):
        entered=threading.Event();release=threading.Event();answers=[];original=server.exclusive
        def held(path,value):entered.set();release.wait(3);return original(path,value)
        match=self.draw();submission=self.submit(match)
        with mock.patch.object(server,'exclusive',side_effect=held):
            job=self.app.start_grade(match['id'],submission['id']);self.assertTrue(entered.wait(2))
            def cancelling():
                try:answers.append(self.app.cancel(match['id'],job['id']))
                except ValueError:answers.append('already completed')
            cancel_thread=threading.Thread(target=cancelling);cancel_thread.start();time.sleep(.05)
            self.assertEqual(answers,[]);release.set();cancel_thread.join(3);self.app.threads[job['id']].join(3)
        self.assertEqual(answers,['already completed'])
        self.assertEqual(self.app.status(match['id'])['job']['status'],'completed')

    def test_source_fingerprint_change_refuses_old_match(self):
        match=self.draw()
        with mock.patch.object(storage,'fingerprints',return_value={'changed':'sha'}):
            with self.assertRaisesRegex(ValueError,'evaluator changed'):self.store.verify_draw(match['id'])

    def test_independent_efficiency_review_is_bound_frozen_and_not_self_reported(self):
        match=self.draw();metrics=self.root/'self-metrics.json';metrics.write_text(json.dumps({'source':'host','total_ms':1}))
        submission=self.submit(match,metrics_path=str(metrics));self.grade(match,submission)
        self.assertFalse(self.app.status(match['id'])['submissions'][0]['efficiency_eligible'])
        evidence=self.root/'independent-host.json';evidence.write_text('{"start_ms":1000,"end_ms":901000}')
        review={'artifact_type':'codex-arena-review','reviewer':'Codex','independent_evidence_verified':True,
                'binding':self.store.review_binding(match['id'],submission['id']),
                'verified_metrics':{'total_ms':900000},
                'evidence_files':[{'kind':'host_log','path':str(evidence),'sha256':storage.digest(evidence)}]}
        path=self.root/'review.json';path.write_text(json.dumps(review))
        bad=json.loads(json.dumps(review));bad['binding']['quality_sha256']='wrong';path.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError,'does not bind'):self.store.import_review(path)
        path.write_text(json.dumps(review));self.store.import_review(path)
        row=self.app.status(match['id'])['submissions'][0]
        self.assertTrue(row['efficiency_eligible']);self.assertAlmostEqual(row['efficiency_score'],60)
        self.assertEqual(self.store.leaderboard(match['id'])['entries'][0]['efficiency_relative_score'],100)
        with self.assertRaises(FileExistsError):self.store.import_review(path)


class ActualLifecycleTests(unittest.TestCase):
    def test_r3_draw_seal_policy_real_background_grade(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();store=storage.ArenaStore(root/'arena')
            app=server.ArenaApp(store)
            try:
                match=store.create_draw('R3','bronze');source=store.folder(match['id'])/'public'/'policy.py'
                submission=store.submit(match['id'],'public-starter',source,'policy.py')
                job=app.start_grade(match['id'],submission['id']);app.threads[job['id']].join(25)
                self.assertFalse(app.threads[job['id']].is_alive())
                status=app.status(match['id']);self.assertEqual(status['job']['status'],'completed',status['job'])
                report=store.reports(match['id'])['reports'][0]
                self.assertTrue(report['valid']);self.assertEqual(report['cases_count'],1)
                self.assertGreater(report['raw_score'],0);self.assertFalse(report['efficiency_eligible'])
            finally:
                app.close()
                for path in root.rglob('*'):
                    if path.is_dir():path.chmod(0o755)

    def test_launcher_ready_and_duplicate_launch_reuses_pid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()/'中文 空格';root.mkdir()
            code='import sys; from pathlib import Path; import arena.server as s; s.ROOT=Path(sys.argv[1]); raise SystemExit(s.main(["--no-open"]))'
            command=[sys.executable,'-B','-c',code,str(root)]
            environment=dict(os.environ,PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1')
            first=subprocess.Popen(command,cwd=root,env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                ready,_,_=select.select([first.stdout],[],[],5);self.assertTrue(ready)
                original=json.loads(first.stdout.readline());self.assertTrue(original['ready'])
                second=subprocess.run(command,cwd=root,env=environment,capture_output=True,text=True,timeout=6)
                self.assertEqual(second.returncode,0,second.stderr)
                reused=json.loads(second.stdout);self.assertTrue(reused['reused']);self.assertEqual(reused['pid'],original['pid'])
            finally:
                first.terminate()
                try:first.communicate(timeout=5)
                except subprocess.TimeoutExpired:first.kill();first.communicate(timeout=2)


if __name__=='__main__':unittest.main()
