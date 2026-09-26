"""Faulty generation-aware store: a delayed compaction can be promoted into a new epoch."""
import json
import os
from pathlib import Path
import tempfile


class GenerationStore:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/'CURRENT.json'
        if not self.path.exists():self._write({'epoch':0,'version':0,'data':{},'receipts':{}})
    def _read(self):return json.loads(self.path.read_text())
    def _write(self,value):
        fd,temp=tempfile.mkstemp(dir=self.root,prefix='.publish-')
        try:
            with os.fdopen(fd,'w') as file:json.dump(value,file);file.flush();os.fsync(file.fileno())
            os.replace(temp,self.path)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    def commit(self,txid,updates):
        state=self._read();payload=json.dumps(updates,sort_keys=True)
        if txid in state['receipts']:
            previous,version=state['receipts'][txid]
            if previous!=payload:raise ValueError('request conflict')
            return version
        state['version']+=1
        for key,value in updates.items():
            if value is None:state['data'].pop(key,None)
            else:state['data'][key]=value
        state['receipts'][txid]=[payload,state['version']];self._write(state);return state['version']
    def snapshot(self):return self._read()['data']
    def prepare_compaction(self):return self._read()
    def migrate_writer(self):
        state=self._read();state['epoch']+=1;self._write(state);return state['epoch']
    def publish_compaction(self,token):
        current=self._read();token=json.loads(json.dumps(token))
        token['epoch']=current['epoch'];self._write(token);return True
