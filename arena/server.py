#!/usr/bin/env python3
"""Standard-library loopback match launcher, with explicit sealing and independent grading."""
from __future__ import annotations
import argparse
import fcntl
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import math
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import signal
from socketserver import TCPServer
import sys
import threading
import time
from urllib.parse import urlsplit,unquote
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from arena.storage import ArenaStore,atomic,exclusive,entrypoint,identity,now,read,writable


class ArenaApp:
    def __init__(self,store=None,*,grader=None,catalog_factory=None):
        self.store=store or ArenaStore();self.grader=grader;self.catalog_factory=catalog_factory
        self.csrf=secrets.token_urlsafe(32);self.instance=secrets.token_hex(16)
        self.lock=threading.RLock();self.jobs={};self.threads={};self.cancel_events={};self.closed=False
        # A crashed host never silently claims its old in-flight evaluation completed.
        for path in self.store.matches.glob('*/private/jobs/*/status.json'):
            state=read(path)
            if state.get('status') in ('queued','running'):
                state.update(status='failed',error='host restarted before completion',finished_at=now())
                atomic(path,state)

    def catalog(self):
        if self.catalog_factory:catalog=self.catalog_factory()
        else:
            from arena.rules import catalog as generate
            catalog=generate()
        result=json.loads(json.dumps(catalog))
        for tier in result.get('tiers',[]):tier.setdefault('label',tier.get('name',tier['id']))
        return result

    def bootstrap(self):return dict(self.catalog(),csrf=self.csrf,instance=self.instance,matches=self.store.list_matches())

    def _job_view(self,job):
        view={key:value for key,value in job.items() if not key.startswith('_')}
        if job.get('_started_monotonic') is not None:
            end=job.get('_ended_monotonic') or time.monotonic()
            view['elapsed_seconds']=round(end-job['_started_monotonic'],3)
        else:view.setdefault('elapsed_seconds',0)
        return view

    def status(self,match_id):
        match=self.store.public_match(match_id)
        with self.lock:
            candidates=[job for job in self.jobs.values() if job['match_id']==match_id]
            job=max(candidates,key=lambda item:item['created_at']) if candidates else None
            if job is None:
                files=sorted(self.store.folder(match_id).glob('private/jobs/*/status.json'))
                if files:job=read(files[-1])
            match['job']=self._job_view(job) if job else None
        if job and job['status'] in ('queued','running'):
            for submission in match['submissions']:
                if submission['id']==job['submission_id']:submission['status']='grading'
        leaderboard=self.store.leaderboard(match_id)
        relative={row['id']:row['relative_score'] for row in leaderboard['entries']}
        for submission in match['submissions']:submission['relative_score']=relative.get(submission['id'])
        return match

    def _persist_job(self,job):
        path=self.store.folder(job['match_id'])/'private'/'jobs'/job['id']/'status.json'
        atomic(path,self._job_view(job))

    def start_grade(self,match_id,sid):
        identity(sid);self.store.verify_submission(match_id,sid)
        with self.lock:
            if self.closed:raise RuntimeError('server is shutting down')
            if any(j['match_id']==match_id and j['status'] in ('queued','running') for j in self.jobs.values()):
                raise ValueError('this match already has an active grading job')
            job_id='j-'+str(time.time_ns())+'-'+secrets.token_hex(3)
            job={'id':job_id,'match_id':match_id,'submission_id':sid,'status':'queued','created_at':now(),
                 'progress':{'phase':'queued','message':'等待独立自动检验'},'_started_monotonic':None}
            self.jobs[job_id]=job;event=threading.Event();self.cancel_events[job_id]=event;self._persist_job(job)
            thread=threading.Thread(target=self._grade,args=(job_id,),name=job_id,daemon=True)
            self.threads[job_id]=thread;thread.start()
            return self._job_view(job)

    def _grade(self,job_id):
        job=self.jobs[job_id];match_id=job['match_id'];sid=job['submission_id'];event=self.cancel_events[job_id]
        def progress(value):
            with self.lock:
                # Progress carries public case indexes/messages, not command lines/seeds.
                safe={key:value[key] for key in ('phase','message','case_index','case_count') if key in value}
                job['progress']=self.store._redact(match_id,safe);self._persist_job(job)
        try:
            with self.lock:
                job.update(status='running',_started_monotonic=time.monotonic(),started_at=now())
                job['progress']={'phase':'verify','message':'核对抽签与答案封存摘要'};self._persist_job(job)
            record=self.store.verify_draw(match_id);sealed,manifest=self.store.verify_submission(match_id,sid)
            work=self.store.folder(match_id)/'private'/'jobs'/job_id;work.mkdir(parents=True,exist_ok=True)
            evaluation=work/'evaluation';shutil.copytree(sealed/'payload',evaluation);writable(evaluation)
            candidate=entrypoint(evaluation,manifest['entrypoint']);metrics=read(sealed/'metrics.json')
            if event.is_set():raise InterruptedError('cancelled before evaluator launch')
            if self.grader:grader=self.grader
            else:
                from arena.judge import grade_match
                grader=grade_match
            result=grader(record['private'],candidate,work/'output',timeout=600,metrics=metrics,
                          verified_metrics=False,cancel_event=event,progress=progress)
            self.store.verify_submission(match_id,sid)
            if event.is_set():raise InterruptedError('grading cancelled')
            if not isinstance(result,dict):raise ValueError('grader did not return a result object')
            result.update(graded_at=now(),submission_id=sid,participant=manifest['participant'],
                          metrics_trust='unverified',efficiency_eligible=False,metrics=metrics,grade_id=job_id)
            official_path=self.store.folder(match_id)/'private'/('official-'+sid+'.json')
            usable=(type(result.get('valid')) is bool and type(result.get('raw_score')) in (int,float)
                    and math.isfinite(result['raw_score']))
            with self.lock:
                # Finalization and cancel share one linearization lock. Once cancel
                # is acknowledged, it is impossible to publish an official result.
                if event.is_set():raise InterruptedError('grading cancelled before official publication')
                result['official']=usable and not official_path.exists()
                if result['official']:
                    exclusive(official_path,result)
                    official_path.chmod(0o444)
                atomic(work/'grade.json',result)
                if not official_path.exists():atomic(self.store.folder(match_id)/'private'/('latest-'+sid+'.json'),result)
                message=('自动检验完成；Codex/视觉/指标核验按报告保留待评项' if result['official'] else
                         '诊断复跑完成；首次官方分保持冻结' if usable else '检验环境未产生可用判分，可修复后重试')
                job.update(status='completed' if usable else 'failed',finished_at=now(),_ended_monotonic=time.monotonic(),
                           official_result=result['official'],diagnostic=usable and not result['official'],
                           progress={'phase':'complete' if usable else 'failed','message':message})
                if not usable:job['error']=str(result.get('status','environment_error'))
                self._persist_job(job)
        except BaseException as exc:
            cancelled=event.is_set() or isinstance(exc,InterruptedError)
            with self.lock:
                job.update(status='cancelled' if cancelled else 'failed',finished_at=now(),_ended_monotonic=time.monotonic(),
                           error=self.store._redact(match_id,str(exc))[:1800],
                           progress={'phase':'cancelled' if cancelled else 'failed','message':'检验已取消' if cancelled else '检验未完成，详见错误'})
                self._persist_job(job)

    def cancel(self,match_id,job_id=None):
        with self.lock:
            jobs=[job for job in self.jobs.values() if job['match_id']==match_id and job['status'] in ('queued','running')]
            if job_id:jobs=[job for job in jobs if job['id']==identity(job_id)]
            if not jobs:raise ValueError('no active owned job to cancel')
            job=jobs[-1];self.cancel_events[job['id']].set()
            job['progress']={'phase':'cancelling','message':'正在终止本次检验拥有的子进程'};self._persist_job(job)
            return self._job_view(job)

    def close(self):
        with self.lock:
            self.closed=True
            for event in self.cancel_events.values():event.set()
        for thread in self.threads.values():thread.join(timeout=3)


class LoopbackServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True
    def server_bind(self):
        TCPServer.server_bind(self);self.server_name='localhost';self.server_port=self.server_address[1]


def make_server(app=None,host='127.0.0.1',port=0,web_root=None):
    if host!='127.0.0.1':raise ValueError('arena only binds 127.0.0.1')
    app=app or ArenaApp();web=Path(web_root or ROOT/'arena'/'web').resolve()
    class Handler(BaseHTTPRequestHandler):
        server_version='LocalArena/0.2'
        def log_message(self,fmt,*args):pass
        def headers_common(self):
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        def reply(self,status,value,content_type='application/json; charset=utf-8',download=None):
            data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode() if content_type.startswith('application/json') else value
            self.send_response(status);self.headers_common();self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(data)))
            if download:self.send_header('Content-Disposition','attachment; filename="'+download+'"')
            self.end_headers();self.wfile.write(data)
        def error(self,status,message):self.reply(status,{'error':{'code':status,'message':str(message)}})
        def check_host(self):
            expected={'127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port)}
            if self.headers.get('Host') not in expected:raise PermissionError('unrecognized Host; use the printed loopback URL')
        def check_post(self):
            self.check_host();origin=self.headers.get('Origin')
            if origin and origin not in {'http://127.0.0.1:'+str(self.server.server_port),'http://localhost:'+str(self.server.server_port)}:
                raise PermissionError('cross-origin mutation refused')
            token=self.headers.get('X-Arena-CSRF','')
            if not secrets.compare_digest(token,app.csrf):raise PermissionError('missing or invalid CSRF token')
            if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':raise ValueError('application/json required')
        def parts(self):return [unquote(part) for part in urlsplit(self.path).path.split('/') if part]
        def do_GET(self):
            try:
                self.check_host();parts=self.parts()
                if parts==['api','health']:return self.reply(200,{'ok':True,'instance':app.instance})
                if parts==['api','bootstrap']:return self.reply(200,app.bootstrap())
                if parts==['api','matches']:return self.reply(200,{'matches':app.store.list_matches()})
                if len(parts)>=3 and parts[:2]==['api','matches']:
                    if len(parts) not in (3,4):raise FileNotFoundError('unknown match endpoint')
                    mid=identity(parts[2]);action=parts[3] if len(parts)==4 else 'status'
                    if action=='status':return self.reply(200,app.status(mid))
                    if action=='leaderboard':return self.reply(200,app.store.leaderboard(mid))
                    if action=='report':
                        reports=app.store.reports(mid);relative={r['id']:r['relative_score'] for r in app.store.leaderboard(mid)['entries']}
                        for row in reports['reports']:row['relative_score']=relative.get(row['id'])
                        return self.reply(200,reports)
                    if action=='download':
                        app.store.verify_draw(mid)
                        return self.reply(200,(app.store.folder(mid)/'public.zip').read_bytes(),'application/zip',mid+'-public.zip')
                    if action=='grading-request':return self.reply(200,app.store.grading_request(mid).encode(),'text/markdown; charset=utf-8','GRADING_REQUEST.md')
                    raise FileNotFoundError('unknown match endpoint')
                if parts and parts[0]=='api':raise FileNotFoundError('unknown endpoint')
                target=(web/('/'.join(parts) or 'index.html')).resolve()
                if not target.is_relative_to(web) or target.is_symlink() or not target.is_file():raise FileNotFoundError('page not found')
                content_type=mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
                return self.reply(200,target.read_bytes(),content_type+'; charset=utf-8' if content_type.startswith('text/') or content_type=='application/javascript' else content_type)
            except PermissionError as exc:self.error(403,exc)
            except FileNotFoundError as exc:self.error(404,exc)
            except (ValueError,KeyError,TypeError) as exc:self.error(400,exc)
            except Exception as exc:self.error(500,type(exc).__name__+': '+str(exc))
        def do_POST(self):
            try:
                self.check_post();length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=1024*1024:raise ValueError('JSON request must be 1 byte to 1 MiB')
                from integrations.cli import read_json
                body=read_json(self.rfile.read(length).decode())
                if type(body) is not dict:raise ValueError('JSON object required')
                parts=self.parts()
                if parts==['api','draw']:
                    result=app.store.create_draw(body['task_id'],body['tier'],body.get('track','all'));return self.reply(201,result)
                if len(parts)==4 and parts[:2]==['api','matches']:
                    mid=identity(parts[2]);action=parts[3]
                    if action=='submit':return self.reply(201,app.store.submit(mid,body['participant'],body['source_path'],body.get('entrypoint'),body.get('metrics_path')))
                    if action=='grade':return self.reply(202,app.start_grade(mid,body['submission_id']))
                    if action=='cancel':return self.reply(202,app.cancel(mid,body.get('job_id')))
                raise FileNotFoundError('unknown mutation endpoint')
            except PermissionError as exc:self.error(403,exc)
            except FileNotFoundError as exc:self.error(404,exc)
            except (ValueError,KeyError,TypeError) as exc:self.error(400,exc)
            except Exception as exc:self.error(500,type(exc).__name__+': '+str(exc))
        def do_OPTIONS(self):self.error(403,'cross-origin requests are not enabled')
    server=LoopbackServer((host,port),Handler);server.app=app
    return server


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--no-open',action='store_true');parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args(argv)
    if not 0<=args.port<=65535:parser.error('port must be 0..65535')
    root=ROOT/'reports'/'arena';root.mkdir(parents=True,exist_ok=True)
    lock=open(root/'launcher.lock','a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        for _ in range(40):
            try:
                running=read(root/'launcher.json')
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(running['url']+'/api/health',timeout=.5) as response:health=json.load(response)
                if health.get('instance')==running['instance']:
                    print(json.dumps(dict(running,reused=True),ensure_ascii=False),flush=True)
                    if not args.no_open:webbrowser.open(running['url'])
                    return 0
            except (OSError,ValueError,KeyError):pass
            time.sleep(.1)
        raise SystemExit('another launcher holds the lock but is not ready; its PID was not replaced')
    app=ArenaApp(ArenaStore(root));server=make_server(app,port=args.port)
    ready={'ready':True,'pid':os.getpid(),'url':'http://127.0.0.1:'+str(server.server_port),'instance':app.instance,'data_directory':str(root)}
    atomic(root/'launcher.json',ready);print(json.dumps(ready,ensure_ascii=False),flush=True)
    if not args.no_open:webbrowser.open(ready['url'])
    def stop(*_):threading.Thread(target=server.shutdown,daemon=True).start()
    if threading.current_thread() is threading.main_thread():signal.signal(signal.SIGTERM,stop)
    try:server.serve_forever(poll_interval=.1)
    except KeyboardInterrupt:pass
    finally:
        app.close();server.server_close()
        try:
            if read(root/'launcher.json').get('instance')==app.instance:(root/'launcher.json').unlink()
        except (OSError,ValueError):pass
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
    return 0


if __name__=='__main__':raise SystemExit(main())
