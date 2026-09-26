"""Faulty stage-v2 service: recovery artifacts survive cancellation without a revision key."""
import json
from pathlib import Path
import sqlite3
import uuid


class Connection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()


class BuildService:
    def __init__(self,root):
        root=Path(root);root.mkdir(parents=True,exist_ok=True);self.path=root/'build.sqlite3'
        with self.connect() as c:c.executescript('CREATE TABLE IF NOT EXISTS graphs(project TEXT PRIMARY KEY,revision INTEGER,payload TEXT);'
            'CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,project TEXT,revision INTEGER,payload TEXT,status TEXT,value INTEGER);'
            'CREATE TABLE IF NOT EXISTS recovery(project TEXT PRIMARY KEY,value INTEGER);')
    def connect(self):return sqlite3.connect(self.path,timeout=5,factory=Connection)
    def set_graph(self,project,graph):
        with self.connect() as c:
            row=c.execute('SELECT revision FROM graphs WHERE project=?',(project,)).fetchone();revision=0 if row is None else row[0]+1
            c.execute('INSERT OR REPLACE INTO graphs VALUES(?,?,?)',(project,revision,json.dumps(graph)))
        return revision
    def enqueue(self,project):
        with self.connect() as c:
            revision,payload=c.execute('SELECT revision,payload FROM graphs WHERE project=?',(project,)).fetchone();jid=uuid.uuid4().hex
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,NULL)',(jid,project,revision,payload,'pending'))
        return jid
    def cancel(self,jid):
        with self.connect() as c:c.execute("UPDATE jobs SET status='cancelled' WHERE id=? AND status NOT IN ('done','cancelled')",(jid,))
    def run(self,jid,hook=None):
        with self.connect() as c:
            project,revision,payload,status,value=c.execute('SELECT project,revision,payload,status,value FROM jobs WHERE id=?',(jid,)).fetchone()
            if status in ('done','cancelled'):return {'status':status,'value':value,'revision':revision}
            row=c.execute('SELECT value FROM recovery WHERE project=?',(project,)).fetchone()
            spec=json.loads(payload);value=row[0] if row else sum(spec['inputs'])*spec['factor']
            c.execute('INSERT OR REPLACE INTO recovery VALUES(?,?)',(project,value));c.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,))
        if hook:hook('after_prepare')
        with self.connect() as c:
            status=c.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()[0]
            if status=='cancelled':return {'status':'cancelled','value':None,'revision':revision}
            c.execute("UPDATE jobs SET status='done',value=? WHERE id=?",(value,jid));c.execute('DELETE FROM recovery WHERE project=?',(project,))
        return {'status':'done','value':value,'revision':revision}
    def get(self,jid):
        with self.connect() as c:
            status,value,revision=c.execute('SELECT status,value,revision FROM jobs WHERE id=?',(jid,)).fetchone()
            return {'status':status,'value':value,'revision':revision}
