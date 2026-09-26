"""Legacy persistent build cache. Deliberately contains interacting correctness bugs."""
import json,hashlib
from pathlib import Path
class BuildError(RuntimeError):pass
class CycleError(BuildError):pass
class UnsafePath(BuildError):pass
class Builder:
    def __init__(self,root,cache):self.root=Path(root);self.cache=Path(cache);self.cache.mkdir(parents=True,exist_ok=True);self.memo={};self.stats={}
    def build(self,spec,target,env=None):
        env=env or {};self.stats={'cache_hits':0,'executed':0,'source_bytes':0}
        def go(name):
            if name in self.memo:return self.memo[name]
            n=spec['nodes'][name]
            if n['op']=='source':
                p=self.root/n['path'];data=p.read_bytes();self.memo[name]=data;return data
            data=b''.join(go(d) for d in sorted(n.get('deps',[])))
            key=hashlib.md5((name+str(len(data))).encode()).hexdigest();p=self.cache/key
            if p.exists():self.stats['cache_hits']+=1;return p.read_bytes()
            if n['op']=='upper':data=data.upper()
            elif n['op']=='reverse':data=data[::-1]
            elif n['op']=='sha256':data=hashlib.sha256(data).hexdigest().encode()
            elif n['op']=='envcat':data+=b''.join(str(env.get(k,'')).encode() for k in n.get('env',[]))
            p.write_bytes(data);self.stats['executed']+=1;self.memo[name]=data;return data
        return go(target)
