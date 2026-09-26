"""Legacy implementation. Preserve the API, not the file format.
Import compatibility for single-file runner and package use.
"""
import json
from pathlib import Path
try:
    from .snapshot import Snapshot
    from .codec import encode
except ImportError:
    from snapshot import Snapshot
    from codec import encode
class CorruptionError(RuntimeError):pass
class AlreadyOpen(RuntimeError):pass
class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.mkdir(parents=True,exist_ok=True);self.file=self.path/'state.json'
        try:obj=json.loads(self.file.read_text());self.data=obj['data'];self.version=obj['version']
        except (FileNotFoundError,json.JSONDecodeError):self.data={};self.version=0
    def commit(self,txid,ops):
        for op in ops:
            if op['op']=='put':self.data[op['key']]=op['value']
            elif op['op']=='del':self.data.pop(op['key'],None)
            else:raise ValueError('unsupported')
        self.version+=1;self.file.write_text(encode({'data':self.data,'version':self.version}));return self.version
    def get(self,key):return self.data.get(key)
    def snapshot(self):return Snapshot(self.data,self.version)
    def compact(self):pass
    def close(self):pass
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
