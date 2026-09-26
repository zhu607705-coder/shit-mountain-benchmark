"""Project-scoped jobs; enqueue freezes a graph snapshot transactionally."""
import json,time,uuid
from .db import connect


class Problem(Exception):
    def __init__(self,status,message):self.status,self.message=status,message


def graph(value):
    if not isinstance(value,dict) or not isinstance(value.get('nodes'),dict) or not isinstance(value.get('aliases',{}),dict):raise Problem(400,'nodes and aliases must be objects')
    return json.dumps(dict(nodes=value['nodes'],aliases=value.get('aliases',{})),ensure_ascii=False,sort_keys=True)


def save_project(config,pid,value):
    if not pid or len(pid)>100:raise Problem(400,'invalid project id')
    payload=graph(value)
    with connect(config) as c:
        c.execute('INSERT INTO projects(id,graph,revision) VALUES(?,?,0) ON CONFLICT(id) DO UPDATE SET graph=excluded.graph,revision=projects.revision+1',(pid,payload))
    return {'ok':True,'project_id':pid}


def enqueue(config,pid,target):
    if not isinstance(target,str) or not target:raise Problem(400,'target must be nonempty string')
    with connect(config) as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT graph FROM projects WHERE id=?',(pid,)).fetchone()
        if row is None:raise Problem(404,'project not found')
        jid=uuid.uuid4().hex;now=time.time()
        c.execute("INSERT INTO jobs(id,project_id,target,status,payload,created,updated) VALUES(?,?,?,'pending',?,?,?)",(jid,pid,target,row['graph'],now,now))
        c.execute('COMMIT')
    return {'id':jid,'project_id':pid,'status':'pending'}


def get_job(config,pid,jid):
    with connect(config) as c:row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
    if row is None:raise Problem(404,'job not found')
    return {k:(json.loads(row[k]) if row[k] else None) if k=='result' else row[k] for k in ['id','project_id','target','status','result','error']}


def cancel(config,pid,jid):
    with connect(config) as c:
        result=c.execute("UPDATE jobs SET cancel_requested=1,status=CASE WHEN status='pending' THEN 'cancelled' ELSE status END,updated=? WHERE id=? AND project_id=? AND status IN ('pending','running')",(time.time(),jid,pid))
    # A terminal job is a no-op; an unknown or cross-project job stays inaccessible.
    return get_job(config,pid,jid)
