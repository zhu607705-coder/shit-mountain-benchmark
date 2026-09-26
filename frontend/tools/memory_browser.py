"""Explicit in-memory adapter for about:blank DOM smoke tests.
It does not test browser-native storage, origin, navigation, or download policies.
No browser policy is changed. Full-origin tests remain in check_frontend.py.
"""
from __future__ import annotations
import json
class MemoryBrowser:
    def __init__(self,context):
        self.context=context;self.local={};self.session={};self.urls={};self.counter=0;self.pending=[];self.delivery_errors=[]
        def write(source,key,value):
            if value is None:self.local.pop(key,None)
            else:self.local[key]=value
            self.pending.append((source['page'],key,value))
        context.expose_binding('_arenaWrite',write)
    def flush(self):
        queued=self.pending;self.pending=[]
        for source,key,value in queued:
            for other in list(self.context.pages):
                if other!=source and not other.is_closed():
                    try:other.evaluate('([k,v])=>window.__arenaRemote?.(k,v)',[key,value])
                    except Exception as exc:self.delivery_errors.append(str(exc))
    def load(self,page,html,url):
        if page in self.urls:
            try:self.session[page]=page.evaluate('window.__arenaDumpSession()')
            except Exception:pass
        self.counter+=1;self.urls[page]=url
        init=json.dumps({'local':self.local,'session':self.session.get(page,{}),'url':url,'uid':self.counter})
        script='''<script>(()=>{const cfg=INIT;const local=new Map(Object.entries(cfg.local)),session=new Map(Object.entries(cfg.session));window.__test_url=cfg.url;let count=0;
for(const [name,m,shared] of [['localStorage',local,true],['sessionStorage',session,false]])Object.defineProperty(window,name,{configurable:true,value:{getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>{m.set(k,String(v));if(shared)window._arenaWrite(k,String(v));},removeItem:k=>{m.delete(k);if(shared)window._arenaWrite(k,null);},key:i=>[...m.keys()][i]??null,get length(){return m.size;}}});
window.__arenaRemote=(k,v)=>{const old=local.get(k)||null;if(v===null)local.delete(k);else local.set(k,v);window.dispatchEvent(new StorageEvent('storage',{key:k,newValue:v,oldValue:old}));};window.__arenaDumpSession=()=>Object.fromEntries(session);
history.replaceState=(_a,_b,u)=>{window.__test_url=new URL(u,window.__test_url).href;};
crypto.randomUUID=()=>`fixture-${cfg.uid}-${++count}`;
URL.createObjectURL=b=>{window.__lastBlob=b;return 'blob:fixture';};URL.revokeObjectURL=()=>{};HTMLAnchorElement.prototype.click=function(){};
})();</script>'''.replace('INIT',init)
        html=html.replace('location.search',"new URL(window.__test_url).search").replace('location.pathname',"new URL(window.__test_url).pathname")
        page.goto('about:blank')
        page.set_content(script+html)
    def reload(self,page,html):self.load(page,html,page.evaluate('window.__test_url'))
