#!/usr/bin/env python3
"""Real loopback HTTP + SQLite + independent worker lifecycle acceptance tests.
Trusted local code only. Not a sandbox. No third-party dependencies or fixed ports.
"""
import argparse,datetime,hashlib,json,os,platform,select,sqlite3,subprocess,sys,tempfile,time,urllib.error,urllib.request
from pathlib import Path

TERMINAL={'done','failed','cancelled'}


def small(value=2):return {'nodes':{'a':{'op':'input','data':[value,value+2]},'root':{'op':'scale','deps':['a'],'factor':3}},'aliases':{'main':'root'}}


class Stack:
    def __init__(self,submission,prefix='',split=False,unicode=False,legacy=False,delay=.10):
        self.submission=submission;self.temp=tempfile.TemporaryDirectory(prefix='c2-env-');self.root=Path(self.temp.name);self.prefix=prefix;self.processes=[];self.logs=[];self.server=None;self.worker=None
        self.config_dir=self.root/('配置 目录' if unicode else 'config');self.config_dir.mkdir()
        self.config=self.config_dir/'service.json';self.db=self.config_dir/('非ASCII数据/状态.sqlite3' if unicode else 'state/service.sqlite3')
        self.config.write_text(json.dumps({'database':str(self.db.relative_to(self.config_dir)),'base_path':prefix,'port':0,'job_delay':delay},ensure_ascii=False))
        self.server_cwd=self.root/'web-cwd' if split else self.config_dir;self.worker_cwd=self.root/'worker-cwd' if split else self.config_dir
        self.server_cwd.mkdir(exist_ok=True);self.worker_cwd.mkdir(exist_ok=True)
        if legacy:self.seed_legacy()
    def seed_legacy(self):
        self.db.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE projects(id TEXT PRIMARY KEY,graph TEXT NOT NULL)')
            c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,target TEXT NOT NULL,status TEXT NOT NULL,result TEXT,error TEXT,created REAL NOT NULL,updated REAL NOT NULL)')
            c.execute('INSERT INTO projects VALUES(?,?)',('legacy',json.dumps(small(5))))
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',('oldjob','legacy','main','pending',None,None,1.,1.))
            c.execute('PRAGMA user_version=1')
    def start(self,kind):
        logfile=open(self.root/f'{kind}-{len(self.logs)}.log','w+');self.logs.append(logfile)
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1')
        proc=subprocess.Popen([sys.executable,str(self.submission/'cli.py'),kind,'--config',str(self.config)],cwd=self.server_cwd if kind=='serve' else self.worker_cwd,env=env,stdout=subprocess.PIPE,stderr=logfile,text=True)
        self.processes.append(proc)
        ready,_,_=select.select([proc.stdout],[],[],4)
        line=proc.stdout.readline() if ready else ''
        if not line:
            logfile.flush();logfile.seek(0);raise AssertionError(kind+' did not become ready: '+logfile.read()[-1800:])
        status=json.loads(line)
        if kind=='serve':self.server=proc;self.port=status['port']
        else:self.worker=proc
    def start_all(self):self.start('serve');self.start('worker')
    def stop(self,proc,kill=False):
        if proc and proc.poll() is None:
            proc.kill() if kill else proc.terminate()
            try:proc.wait(timeout=2)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=2)
        if proc and proc.stdout:proc.stdout.close()
    def request(self,path,body=None):
        data=None if body is None else json.dumps(body).encode()
        req=urllib.request.Request(f'http://127.0.0.1:{self.port}{self.prefix}{path}',data=data,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=2) as resp:return resp.status,json.load(resp)
        except urllib.error.HTTPError as exc:return exc.code,json.load(exc)
    def ok(self,path,body=None):
        status,value=self.request(path,body);assert status==200,(path,status,value);return value
    def project(self,pid='A',value=2):self.ok('/projects/'+pid,small(value))
    def enqueue(self,pid='A',target='main'):return self.ok('/projects/'+pid+'/jobs',{'target':target})['id']
    def wait(self,pid,jid,statuses=TERMINAL,timeout=2.8):
        deadline=time.monotonic()+timeout;last=None
        while time.monotonic()<deadline:
            last=self.ok(f'/projects/{pid}/jobs/{jid}')
            if last['status'] in statuses:return last
            time.sleep(.025)
        raise AssertionError(f'job did not reach {sorted(statuses)}: {last}')
    def done(self,pid,jid,values):
        result=self.wait(pid,jid);assert result['status']=='done',result;assert result['result']=={'value':values},result
        return result
    def close(self):
        for proc in reversed(self.processes):self.stop(proc)
        for logfile in self.logs:logfile.close()
        self.temp.cleanup()


def execute(submission,name,options,test):
    stack=None;start=time.monotonic()
    try:
        stack=Stack(submission,**options);stack.start_all();test(stack)
        return {'name':name,'passed':True,'seconds':round(time.monotonic()-start,4)}
    except Exception as exc:return {'name':name,'passed':False,'seconds':round(time.monotonic()-start,4),'error':type(exc).__name__+': '+str(exc)}
    finally:
        if stack:stack.close()


def ordinary(s):
    assert s.ok('/health')['ok'];s.project();s.done('A',s.enqueue(),[6,12])

def isolation(s):
    s.project('A',1);s.project('B',9);a=s.enqueue('A');b=s.enqueue('B');s.done('A',a,[3,9]);s.done('B',b,[27,33]);status,_=s.request('/projects/B/jobs/'+a);assert status==404,('cross-project read',status)

def cancellation(s):
    s.project();jid=s.enqueue();s.wait('A',jid,{'running'});s.ok('/projects/A/jobs/'+jid+'/cancel',{});r=s.wait('A',jid);assert r['status']=='cancelled',r;s.done('A',s.enqueue(),[6,12])

def repair(s):
    s.ok('/projects/A',{'nodes':{'bad':{'op':'fail'},'root':{'op':'sum','deps':['bad']}},'aliases':{'main':'root'}});r=s.wait('A',s.enqueue());assert r['status']=='failed' and r['error']=='FAILED',r
    s.ok('/projects/A/graph',small(4));s.done('A',s.enqueue(),[12,18])

def snapshot(s):
    s.project(value=1);old=s.enqueue();s.wait('A',old,{'running'});s.ok('/projects/A/graph',small(9));s.done('A',old,[3,9]);s.done('A',s.enqueue(),[27,33])

def persistence(s):
    s.project();jid=s.enqueue();s.done('A',jid,[6,12]);s.stop(s.server);s.stop(s.worker);s.start_all();s.done('A',jid,[6,12]);s.done('A',s.enqueue(),[6,12])

def recovery(s):
    s.project();jid=s.enqueue();s.wait('A',jid,{'running'});s.stop(s.worker,kill=True);s.start('worker');s.done('A',jid,[6,12])

def migration(s):
    s.done('legacy','oldjob',[15,21]);s.done('legacy',s.enqueue('legacy'),[15,21])
    with sqlite3.connect(s.db) as c:assert c.execute('PRAGMA user_version').fetchone()[0]==2


def main():
    p=argparse.ArgumentParser();p.add_argument('--submission',required=True);p.add_argument('--output');a=p.parse_args();root=Path(__file__).resolve().parent;submission=Path(a.submission);submission=submission.resolve() if submission.is_absolute() else (root/submission).resolve()
    cases=[('default_business_flow',{},ordinary),('configured_base_path',{'prefix':'/build/v2'},ordinary),('different_process_workdirs',{'split':True},ordinary),('unicode_data_directory',{'unicode':True},ordinary),('project_isolation',{},isolation),('cancel_running_then_retry',{'delay':.35},cancellation),('dependency_failure_then_repair',{},repair),('enqueue_snapshot_isolation',{'delay':.35},snapshot),('server_restart_persistence',{},persistence),('worker_crash_recovery',{'delay':.35},recovery),('legacy_schema_migration',{'legacy':True},migration)]
    results=[execute(submission,*case) for case in cases];passed=sum(r['passed'] for r in results);critical={'default_business_flow','project_isolation','server_restart_persistence','legacy_schema_migration'}
    result={'benchmark':'C2-repository','version':'0.2.0','measured_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'suite_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'submission_sha256':hashlib.sha256(b''.join(str(p.relative_to(submission)).encode()+p.read_bytes() for p in sorted(submission.rglob('*.py')))).hexdigest(),'environment':{'python':platform.python_version(),'platform':platform.platform()},'submission':str(submission),'valid':all(r['passed'] for r in results if r['name'] in critical),'environment_score':round(70*passed/len(results),6),'environment_passed':passed,'environment_total':len(results),'raw_score':None,'selftest_score':None,'selftest_status':'pending organizer review; do not infer a score from this harness','critical_cases':sorted(critical),'tests':results,'process_model':'real HTTP server and worker subprocesses; temporary SQLite DBs; no fixed ports; automatic cleanup','security':'trusted local prototype, not a sandbox'}
    output=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)
    if a.output:(root/a.output).write_text(output+'\n')
    print(output)
if __name__=='__main__':main()
