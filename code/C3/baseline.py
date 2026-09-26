"""Conservative CrashKV baseline. POSIX, Python standard library.
Append-only checksummed frames; one fsync per transaction; atomic compaction.
Snapshots copy all keys. This is deliberately not an optimized storage engine.
"""
from __future__ import annotations
import fcntl,hashlib,json,os,struct,threading,uuid,zlib
from pathlib import Path

HEADER=struct.Struct('!II')
MAX_FRAME=64*1024*1024
BASELINE_FORMAT_DIAGNOSTICS=True
class CorruptionError(RuntimeError):pass
class AlreadyOpen(RuntimeError):pass


def _bytes(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')

def _frame(obj):
    body=_bytes(obj)
    if len(body)>MAX_FRAME:raise ValueError('transaction too large')
    return HEADER.pack(len(body),zlib.crc32(body)&0xffffffff)+body

def _writeall(fd,buf):
    view=memoryview(buf)
    while view:
        n=os.write(fd,view)
        if n<=0:raise OSError('short write')
        view=view[n:]

def _syncdir(path):
    fd=os.open(path,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)

class Snapshot:
    def __init__(self,data,version):self._data=data.copy();self.version=version
    def get(self,key):return self._data.get(key)
    def scan(self,prefix=''):
        return [(k,self._data[k]) for k in sorted(self._data) if k.startswith(prefix)]

class Store:
    def __init__(self,path):
        self.path=Path(path).resolve();self.path.mkdir(parents=True,exist_ok=True)
        self._lock=threading.RLock();self._closed=False;self._failed=False
        self.lockfd=os.open(self.path/'LOCK',os.O_RDWR|os.O_CREAT,0o600)
        try:fcntl.flock(self.lockfd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.lockfd);raise AlreadyOpen(str(path))
        self.data={};self.version=0;self.txids={}
        try:
            self.fd=os.open(self.path/'data.wal',os.O_RDWR|os.O_CREAT|os.O_APPEND,0o600)
            self._recover();_syncdir(self.path)
        except BaseException:
            if hasattr(self,'fd'):os.close(self.fd)
            os.close(self.lockfd);raise

    def _recover(self):
        with open(self.path/'data.wal','rb') as f:
            good=0
            while True:
                header=f.read(HEADER.size)
                if not header:break
                if len(header)<HEADER.size:break
                n,crc=HEADER.unpack(header)
                if n>MAX_FRAME:raise CorruptionError('frame length outside contract')
                body=f.read(n)
                if len(body)<n:break
                if zlib.crc32(body)&0xffffffff!=crc:raise CorruptionError('checksum mismatch')
                try:obj=json.loads(body)
                except Exception as e:raise CorruptionError('invalid payload') from e
                if obj.get('kind')=='snapshot':
                    if good!=0:raise CorruptionError('snapshot not first frame')
                    self.data=obj['data'];self.version=obj['version'];self.txids=obj['txids']
                else:
                    if obj['version']!=self.version+1:raise CorruptionError('version discontinuity')
                    self._apply(obj['ops']);self.version=obj['version']
                    self.txids[obj['txid']]=[obj['digest'],self.version]
                good=f.tell()
        # Only a physically incomplete suffix is truncated. A complete bad CRC is not.
        if os.fstat(self.fd).st_size!=good:os.ftruncate(self.fd,good);os.fsync(self.fd)

    def _apply(self,ops):
        result=self.data.copy()
        for op in ops:
            if op['op']=='put':result[op['key']]=op['value']
            else:result.pop(op['key'],None)
        self.data=result

    def commit(self,txid:str,ops:list[dict])->int:
        with self._lock:
            self._check()
            if not isinstance(txid,str) or not txid or not isinstance(ops,list) or not 1<=len(ops)<=1024:
                raise ValueError('bad transaction')
            for op in ops:
                if not isinstance(op,dict) or op.get('op') not in ('put','del') or not isinstance(op.get('key'),str):raise ValueError('bad operation')
                if op['op']=='put' and not isinstance(op.get('value'),str):raise ValueError('value must be str')
                required={'op','key','value'} if op['op']=='put' else {'op','key'}
                if set(op)!=required:raise ValueError('unknown/missing fields')
            # Copy via the canonical serialization before accepting mutable client objects.
            clean=json.loads(_bytes(ops));digest=hashlib.sha256(_bytes(clean)).hexdigest()
            if txid in self.txids:
                old,v=self.txids[txid]
                if old!=digest:raise ValueError('txid conflict')
                return v
            obj={'kind':'txn','txid':txid,'digest':digest,'ops':clean,'version':self.version+1}
            encoded=_frame(obj)
            try:
                _writeall(self.fd,encoded);os.fsync(self.fd)
                self._apply(clean);self.version+=1;self.txids[txid]=[digest,self.version]
                return self.version
            except BaseException:
                # The WAL may contain a partial or durable-but-unpublished frame.
                # Further acknowledgements require recovery from a fresh handle.
                self._failed=True
                raise

    def _check(self):
        if self._closed:raise RuntimeError('store is closed')
        if self._failed:raise RuntimeError('store requires close and reopen after I/O failure')
    def get(self,key):
        with self._lock:self._check();return self.data.get(key)
    def snapshot(self):
        with self._lock:self._check();return Snapshot(self.data,self.version)
    def compact(self):
        with self._lock:
            self._check()
            tmp=self.path/('.compact-'+uuid.uuid4().hex)
            encoded=_frame({'kind':'snapshot','data':self.data,'version':self.version,'txids':self.txids})
            fd=None
            try:
                fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                _writeall(fd,encoded);os.fsync(fd);os.close(fd);fd=None
                os.replace(tmp,self.path/'data.wal');_syncdir(self.path)
                old=self.fd;self.fd=os.open(self.path/'data.wal',os.O_RDWR|os.O_APPEND);os.close(old)
            except BaseException:
                # replace may already have published a new inode; never append
                # to the previous, possibly unlinked descriptor after failure.
                self._failed=True
                raise
            finally:
                if fd is not None:os.close(fd)
                try:tmp.unlink()
                except FileNotFoundError:pass
    def close(self):
        with self._lock:
            if not self._closed:os.close(self.fd);os.close(self.lockfd);self._closed=True
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
