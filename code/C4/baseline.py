"""Content-addressed, single-process baseline for a hermetic DAG build DSL.
Always rehashes reachable sources; outputs are published by atomic rename.
Multiple OS processes may safely share the cache. Dependencies preserve order.
"""
from __future__ import annotations
import base64,hashlib,json,os,tempfile
from pathlib import Path
class BuildError(RuntimeError):pass
class CycleError(BuildError):pass
class UnsafePath(BuildError):pass


def digest(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def canonical(obj):return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()

class Builder:
    def __init__(self,root,cache):
        self.root=Path(root).resolve();self.cache=Path(cache).resolve();self.cache.mkdir(parents=True,exist_ok=True)
        self.stats={}
    def build(self,spec:dict,target:str,env:dict|None=None)->bytes:
        env=env or {};nodes=spec['nodes'];memo={};visiting=set()
        self.stats={'cache_hits':0,'executed':0,'source_bytes':0}
        def evaluate(name):
            if name in memo:return memo[name]
            if name in visiting:raise CycleError(name)
            if name not in nodes:raise BuildError('unknown dependency: '+name)
            visiting.add(name);node=nodes[name];op=node['op']
            if op=='source':
                try:p=(self.root/node['path']).resolve()
                except (OSError,RuntimeError) as e:raise BuildError('unresolvable source path') from e
                try:p.relative_to(self.root)
                except ValueError:raise UnsafePath(node['path'])
                try:data=p.read_bytes()
                except OSError as e:raise BuildError('unreadable source: '+node['path']) from e
                self.stats['source_bytes']+=len(data)
                # Path identity remains explicit, although equal bytes are reusable.
                key=digest(canonical({'schema':1,'node':node,'content':digest(data)}))
            else:
                deps=[evaluate(d) for d in node.get('deps',[])]
                bindings={k:env.get(k,'') for k in node.get('env',[])}
                key=digest(canonical({'schema':1,'node':node,'dependencies':[k for k,_ in deps],'env':bindings}))
                path=self.cache/(key+'.json');data=None
                try:
                    stored=json.loads(path.read_bytes());raw=base64.b64decode(stored['data'],validate=True)
                    if stored['key']==key and stored['digest']==digest(raw):data=raw;self.stats['cache_hits']+=1
                except (OSError,ValueError,KeyError,TypeError):pass
                if data is None:
                    chunks=[d for _,d in deps]
                    sep=node.get('separator','').encode('utf-8');joined=sep.join(chunks)
                    if op=='concat':data=joined
                    elif op in ('upper','reverse'):
                        try:text=joined.decode('utf-8')
                        except UnicodeError as e:raise BuildError('text operation requires UTF-8 input') from e
                        data=(text.upper() if op=='upper' else text[::-1]).encode('utf-8')
                    elif op=='sha256':data=digest(joined).encode('ascii')
                    elif op=='envcat':data=node.get('prefix','').encode()+joined+b''.join(str(bindings[k]).encode() for k in node.get('env',[]))
                    else:raise BuildError('unknown op: '+op)
                    self.stats['executed']+=1
                    payload=canonical({'key':key,'digest':digest(data),'data':base64.b64encode(data).decode()})
                    fd,tmp=tempfile.mkstemp(prefix='.publish-',dir=self.cache)
                    try:
                        with os.fdopen(fd,'wb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
                        os.replace(tmp,path)
                    finally:
                        if os.path.exists(tmp):os.unlink(tmp)
            visiting.remove(name);memo[name]=(key,data);return key,data
        return evaluate(target)[1]
