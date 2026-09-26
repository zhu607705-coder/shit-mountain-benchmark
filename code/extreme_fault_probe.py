#!/usr/bin/env python3
"""Actual filesystem and subprocess probes. Independent of any candidate WAL format."""
from __future__ import annotations
import argparse
import concurrent.futures
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import sys
import threading


def load(path):
    path=Path(path);sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location('candidate',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def ops(value):
    return [dict(op='put',key='left',value=value),dict(op='put',key='right',value=value),dict(op='del',key='old')]


def initial(store):
    store.commit('stable',[dict(op='put',key='old',value='retained'),dict(op='put',key='base',value='acknowledged')])


def save_receipt(path,receipt,original):
    # Control-plane record uses original calls outside the injected candidate data directory.
    data=json.dumps(receipt).encode();fd=original['open'](str(path),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    try:
        offset=0
        while offset<len(data):offset+=original['write'](fd,data[offset:])
        original['fsync'](fd)
    finally:original['close'](fd)


def fault(module,root,arguments):
    root.mkdir(parents=True,exist_ok=True);directory=root/'store';store=module.Store(directory);initial(store)
    cut=arguments['cut'];mode=arguments['mode'];is_compact=cut.startswith('compact') or cut in ('replace','dirsync')
    snapshot=store.snapshot()
    receipt=dict(intercepted=False,cut=cut,mode=mode,ack_pending=False,ack_followup=False)
    # Each history changes the durable prefix and compaction/tombstone/retry ordering.
    # Full is not 12 copies of an identical empty store.
    prefix={}
    for i in range(arguments['history']):
        key='prefix-'+str(i);previous='prefix-'+str(i-1)
        operations=[dict(op='put',key=key,value=str(i)),dict(op='del',key=previous)]
        version=store.commit('history-'+str(i),operations)
        prefix[key]=str(i);prefix.pop(previous,None)
        if i%2==0:store.compact()
        assert store.commit('history-'+str(i),operations)==version
    receipt['prefix']=prefix;receipt['history']=arguments['history']
    if is_compact:
        store.commit('pending',ops('uncertain'));receipt['ack_pending']=True
    original={name:getattr(os,name) for name in ('write','fsync','replace','open','close')}
    save_receipt(root/'receipt.json',receipt,original)
    fired=False
    def intercept(kind,fn,*args):
        nonlocal fired
        if fired or kind!=cut:return fn(*args)
        fired=True;receipt['intercepted']=True;save_receipt(root/'receipt.json',receipt,original)
        if mode=='before_eio':raise OSError(errno.EIO,'injected before '+kind)
        if mode=='short_enospc':
            if kind.endswith('write'):
                fd,data=args
                if data:fn(fd,data[:max(1,len(data)//3)])
            raise OSError(errno.ENOSPC,'injected bounded space at '+kind)
        result=fn(*args)
        if mode=='kill_after':os.kill(os.getpid(),signal.SIGKILL)
        raise OSError(errno.EIO,'injected after '+kind)
    def wrapped_write(fd,data):return intercept('compact_write' if is_compact else 'commit_write',original['write'],fd,data)
    def wrapped_fsync(fd):
        directory_fd=stat.S_ISDIR(os.fstat(fd).st_mode)
        kind='dirsync' if directory_fd else ('compact_fsync' if is_compact else 'commit_fsync')
        return intercept(kind,original['fsync'],fd)
    def wrapped_replace(source,target):return intercept('replace',original['replace'],source,target)
    os.write=wrapped_write;os.fsync=wrapped_fsync;os.replace=wrapped_replace
    try:
        try:
            if is_compact:store.compact()
            else:
                store.commit('pending',ops('uncertain'));receipt['ack_pending']=True
        except OSError:receipt['operation_raised']=True
        except RuntimeError:receipt['operation_raised']=True
    finally:
        for name,fn in original.items():setattr(os,name,fn)
    # Fail-closed after a damaged write is explicitly acceptable. A returned ACK isn't.
    try:
        store.commit('followup',[dict(op='put',key='followup',value='acknowledged')]);receipt['ack_followup']=True
    except (OSError,RuntimeError):pass
    assert snapshot.get('old')=='retained' and snapshot.get('left') is None,'old snapshot mutated across commit/compact'
    save_receipt(root/'receipt.json',receipt,original);store.close()
    return receipt


def recover(module,root):
    receipt=json.loads((root/'receipt.json').read_text());store=module.Store(root/'store')
    try:
        assert store.get('base')=='acknowledged','lost stable ACK'
        assert store.snapshot().scan('prefix-')==sorted(receipt['prefix'].items()),'lost tombstone/compacted durable prefix'
        left,right,old=store.get('left'),store.get('right'),store.get('old')
        whole=(left=='uncertain' and right=='uncertain' and old is None)
        absent=(left is None and right is None and old=='retained')
        assert whole or absent,dict(left=left,right=right,old=old,error='partial transaction')
        if receipt['ack_pending']:assert whole,'lost pending ACK'
        if receipt['ack_followup']:assert store.get('followup')=='acknowledged','lost post-error ACK'
        v=store.commit('pending',ops('uncertain'));store.compact();store.close()
        store=module.Store(root/'store');assert store.commit('pending',ops('uncertain'))==v,'duplicate version changed'
        try:store.commit('pending',ops('DIFFERENT'))
        except (ValueError,RuntimeError):pass
        else:raise AssertionError('txid conflict lost after recovery+compaction')
        assert store.get('left')=='uncertain' and store.get('right')=='uncertain'
        return dict(durable_prefix=True,uncertain_transaction='whole' if whole else 'absent',
                    retry_version=v,conflict_preserved=True)
    finally:store.close()


def history(module,root,args):
    directory=root/'store';store=module.Store(directory);reference={};receipts={};errors=[]
    try:
        records=args['records']
        for n in range(0,len(records),1024):
            batch=[dict(op='put',key=k,value=v) for k,v in records[n:n+1024]]
            store.commit('initial-'+str(n),batch);reference.update(records[n:n+1024])
        snapshots=[store.snapshot() for _ in range(args['readers'])];frozen=dict(reference)
        # Snapshots are ordinary objects shared by simultaneous threads. The process-level
        # single-writer exclusion is tested separately below; no new read-only API invented.
        barrier=threading.Barrier(args['readers']+1)
        def reader(snapshot):
            barrier.wait()
            for _ in range(5):
                assert snapshot.scan('k')==sorted(frozen.items()),'snapshot drift during writes/compaction'
            return True
        with concurrent.futures.ThreadPoolExecutor(max_workers=args['readers']) as pool:
            futures=[pool.submit(reader,s) for s in snapshots];barrier.wait()
            for index,txn in enumerate(args['transactions']):
                receipts[txn['txid']]=store.commit(txn['txid'],txn['ops'])
                for op in txn['ops']:
                    if op['op']=='put':reference[op['key']]=op['value']
                    else:reference.pop(op['key'],None)
                if index%17==0:store.compact()
            for f in futures:assert f.result()
        assert store.snapshot().scan()==sorted(reference.items())
        # A second OS process must not acquire a writing handle while this handle lives.
        import subprocess
        command=[sys.executable,'-B',__file__,'--submission',str(Path(module.__file__).resolve()),
                 '--root',str(root),'--mode','writer_lock']
        probe=subprocess.run(command,capture_output=True,text=True,timeout=5)
        assert probe.returncode==0,(probe.stdout,probe.stderr)
        store.compact();store.close();store=module.Store(directory)
        for txn in args['transactions']:
            assert store.commit(txn['txid'],txn['ops'])==receipts[txn['txid']]
        assert store.snapshot().scan()==sorted(reference.items())
        return dict(keys=len(records),transactions=len(args['transactions']),snapshot_readers=args['readers'],
                    snapshots_frozen=True,multiprocess_writer_exclusion=True,reopen_idempotency=True)
    finally:store.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--submission',required=True);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--mode',required=True);parser.add_argument('--arguments',default='{}');parser.add_argument('--arguments-file',type=Path);args=parser.parse_args()
    module=load(args.submission);value=json.loads(args.arguments_file.read_text() if args.arguments_file else args.arguments)
    if args.mode=='store_fault':result=fault(module,args.root,value)
    elif args.mode=='store_recover':result=recover(module,args.root)
    elif args.mode=='store_history':result=history(module,args.root,value)
    elif args.mode=='writer_lock':
        try:handle=module.Store(args.root/'store')
        except Exception:result={'writer_lock':True}
        else:handle.close();raise AssertionError('second process acquired live writer lock')
    elif args.mode=='builder':
        spec=json.loads(Path(value['spec']).read_text());data=module.Builder(args.root,Path(value['cache'])).build(spec,'root',value['env'])
        result={'hex':data.hex()}
    else:raise ValueError(args.mode)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
