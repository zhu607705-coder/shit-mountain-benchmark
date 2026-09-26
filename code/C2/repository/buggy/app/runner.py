"""Single worker, durable claims, cooperative cancellation, per-project pure-work caches."""
import json,time
from .db import connect,initialize,recover
from .core.engine import Engine


def claim(config):
    with connect(config) as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY created,id LIMIT 1").fetchone()
        if row:c.execute("UPDATE jobs SET status='running',updated=? WHERE id=?",(time.time(),row['id']))
        c.execute('COMMIT')
        return dict(row) if row else None


def cancelled(config,jid):
    with connect(config) as c:row=c.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()
    return row['status']=='cancelled'


def finish(config,job,status,result=None,error=None):
    with connect(config) as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('UPDATE jobs SET status=?,result=?,error=?,updated=? WHERE id=?',(status,json.dumps(result) if result is not None else None,error,time.time(),job['id']))
        c.execute('COMMIT')


def main(config):
    initialize(config);recover(config);engines={}
    print(json.dumps({'worker_ready':True}),flush=True)
    while True:
        job=claim(config)
        if job is None:time.sleep(.02);continue
        until=time.monotonic()+config['job_delay']
        while time.monotonic()<until and not cancelled(config,job['id']):time.sleep(.01)
        if cancelled(config,job['id']):finish(config,job,'cancelled');continue
        try:
            with connect(config) as c: current=c.execute('SELECT graph FROM projects WHERE id=?',(job['project_id'],)).fetchone()
            payload=current['graph'];spec=json.loads(payload);key=job['project_id']
            prior=engines.get(key)
            if prior is None or prior[0]!=payload:engines[key]=(payload,Engine(spec['nodes'],spec['aliases']))
            result=engines[key][1].step({'op':'build','target':job['target']})
            if 'error' in result:finish(config,job,'failed',error=result['error'])
            else:finish(config,job,'done',result=result)
        except Exception as exc:finish(config,job,'failed',error=type(exc).__name__+': '+str(exc))
