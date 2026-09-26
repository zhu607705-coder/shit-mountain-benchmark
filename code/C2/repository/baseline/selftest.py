#!/usr/bin/env python3
"""Submission-authored regressions: direct module tests, independent of organizer harness."""
import json,sqlite3,tempfile,unittest
from pathlib import Path
from app import config,db,service,runner


class Regressions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='c2-selftest-');self.root=Path(self.temp.name);self.path=self.root/'service.json';self.path.write_text(json.dumps({'database':'data/state.sqlite','base_path':'/api/v2/'}));self.conf=config.load(self.path);db.initialize(self.conf)
    def tearDown(self):self.temp.cleanup()
    def project(self,pid='A',value=1):return service.save_project(self.conf,pid,{'nodes':{'root':{'op':'input','data':[value]}},'aliases':{}})
    def test_relative_database_anchored_to_config(self):self.assertEqual(self.conf['database'],(self.root/'data/state.sqlite').resolve())
    def test_base_path_preserved(self):self.assertEqual(self.conf['base_path'],'/api/v2')
    def test_enqueue_freezes_payload(self):
        self.project(value=1);job=service.enqueue(self.conf,'A','root');self.project(value=9)
        with db.connect(self.conf) as c:payload=json.loads(c.execute('SELECT payload FROM jobs WHERE id=?',(job['id'],)).fetchone()[0])
        self.assertEqual(payload['nodes']['root']['data'],[1])
    def test_foreign_project_cannot_read_job(self):
        self.project();self.project('B');job=service.enqueue(self.conf,'A','root')
        with self.assertRaises(service.Problem) as ctx:service.get_job(self.conf,'B',job['id'])
        self.assertEqual(ctx.exception.status,404)
    def test_cancel_wins_before_publish(self):
        self.project();service.enqueue(self.conf,'A','root');job=runner.claim(self.conf);service.cancel(self.conf,'A',job['id']);runner.finish(self.conf,job,'done',{'value':[1]});result=service.get_job(self.conf,'A',job['id']);self.assertEqual(result['status'],'cancelled');self.assertIsNone(result['result'])
    def test_worker_restart_requeues_running(self):
        self.project();service.enqueue(self.conf,'A','root');job=runner.claim(self.conf);db.recover(self.conf);self.assertEqual(service.get_job(self.conf,'A',job['id'])['status'],'pending')
    def test_core_adapter_is_same_class_as_worker(self):
        from engine import Engine as Export
        self.assertIs(Export,runner.Engine)
    def test_legacy_schema_preserves_graph(self):
        old=dict(self.conf,database=self.root/'old.sqlite')
        with sqlite3.connect(old['database']) as c:
            c.execute('CREATE TABLE projects(id TEXT PRIMARY KEY,graph TEXT NOT NULL)');c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,target TEXT NOT NULL,status TEXT NOT NULL,result TEXT,error TEXT,created REAL NOT NULL,updated REAL NOT NULL)');c.execute('INSERT INTO projects VALUES(?,?)',('legacy',json.dumps({'nodes':{'root':{'op':'input','data':[7]}},'aliases':{}})));c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',('j','legacy','root','pending',None,None,0.,0.))
        db.initialize(old)
        with db.connect(old) as c:
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],2);payload=json.loads(c.execute('SELECT payload FROM jobs').fetchone()[0]);self.assertEqual(payload['nodes']['root']['data'],[7])
if __name__=='__main__':unittest.main()
