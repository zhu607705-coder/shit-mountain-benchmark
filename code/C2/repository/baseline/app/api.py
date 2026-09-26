"""Small loopback HTTP API; routing respects the configured base path."""
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import unquote,urlsplit
from . import service
from .db import initialize


def serve(config):
    initialize(config)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):self.dispatch()
        def do_POST(self):self.dispatch()
        def dispatch(self):
            try:
                path=urlsplit(self.path).path;prefix=config['base_path']
                if prefix and not path.startswith(prefix+'/'):raise service.Problem(404,'route not found')
                parts=[unquote(p) for p in path[len(prefix):].split('/') if p]
                length=int(self.headers.get('Content-Length','0'))
                body=json.loads(self.rfile.read(length)) if length else {}
                if self.command=='GET' and parts==['health']:result={'ok':True,'schema':2}
                elif len(parts)==2 and parts[0]=='projects' and self.command=='POST':result=service.save_project(config,parts[1],body)
                elif len(parts)==3 and parts[0]=='projects' and parts[2]=='graph' and self.command=='POST':result=service.save_project(config,parts[1],body)
                elif len(parts)==3 and parts[0]=='projects' and parts[2]=='jobs' and self.command=='POST':result=service.enqueue(config,parts[1],body.get('target'))
                elif len(parts)==4 and parts[0]=='projects' and parts[2]=='jobs' and self.command=='GET':result=service.get_job(config,parts[1],parts[3])
                elif len(parts)==5 and parts[0]=='projects' and parts[2]=='jobs' and parts[4]=='cancel' and self.command=='POST':result=service.cancel(config,parts[1],parts[3])
                else:raise service.Problem(404,'route not found')
                self.reply(200,result)
            except service.Problem as exc:self.reply(exc.status,{'error':exc.message})
            except (ValueError,TypeError) as exc:self.reply(400,{'error':str(exc)})
            except Exception as exc:self.reply(500,{'error':type(exc).__name__+': '+str(exc)})
        def reply(self,status,payload):
            data=json.dumps(payload,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer((config['host'],config['port']),Handler)
    print(json.dumps({'ready':True,'port':server.server_address[1],'base_path':config['base_path']}),flush=True)
    try:server.serve_forever(poll_interval=.05)
    finally:server.server_close()
