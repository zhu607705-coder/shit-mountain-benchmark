"""Faulty versioned builder: sources are pinned, environment is refreshed before publish."""
import hashlib
import json
import os
from pathlib import Path
import tempfile


class VersionedBuilder:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        for name in ('manifests','blobs','cache'):(self.root/name).mkdir(exist_ok=True)
    def _atomic(self,path,data):
        fd,temp=tempfile.mkstemp(dir=self.root,prefix='.tmp-')
        try:
            with os.fdopen(fd,'wb') as file:file.write(data);file.flush();os.fsync(file.fileno())
            os.replace(temp,path)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    def update(self,sources,env):
        pointers=[]
        for name,data in sources.items():
            digest=hashlib.sha256(data.encode()).hexdigest();self._atomic(self.root/'blobs'/digest,data.encode());pointers.append([name,digest])
        manifest={'sources':sorted(pointers),'env':dict(env)};encoded=json.dumps(manifest,sort_keys=True).encode()
        version=hashlib.sha256(encoded).hexdigest();self._atomic(self.root/'manifests'/version,encoded);self.activate(version);return version
    def activate(self,version):
        if not (self.root/'manifests'/version).is_file():raise ValueError('unknown version')
        self._atomic(self.root/'CURRENT',version.encode())
    def build(self,hook=None):
        version=(self.root/'CURRENT').read_text();cached=self.root/'cache'/version
        if cached.exists():return {'version':version,'data':cached.read_text()}
        manifest=json.loads((self.root/'manifests'/version).read_text())
        pieces=[(self.root/'blobs'/digest).read_text() for _,digest in manifest['sources']]
        if hook:hook('after_sources')
        current=(self.root/'CURRENT').read_text();environment=json.loads((self.root/'manifests'/current).read_text())['env']
        data='|'.join(pieces)+'#'+'|'.join(str(environment[k]) for k in sorted(environment))
        self._atomic(cached,data.encode());return {'version':version,'data':data}
