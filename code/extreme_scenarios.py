"""Deterministic materialized workloads and independent tiny reference computations."""
from __future__ import annotations
import hashlib
import json
import random
from extreme import parameters


def ledger_event(tenant, identity, amount):
    return dict(tenant=tenant,id=identity,kind='post',entries=[['cash',amount],['equity',-amount]])


def graph(nodes, depth, value):
    # Bounded-width output; deep dependency discovery is not giant output allocation.
    data={'n0':dict(op='input',data=[value,value+2])}
    for i in range(1,depth): data['n'+str(i)]=dict(op='scale',deps=['n'+str(i-1)],factor=1)
    for i in range(depth,nodes-1): data['n'+str(i)]=dict(op='sum',deps=['n0'])
    data['root']=dict(op='sum',deps=['n'+str(depth-1)]+['n'+str(i) for i in range(depth,nodes-1)])
    return dict(nodes=data,aliases={'main':'root','previous':'n0'})


def file_graph(nodes, depth):
    data={'n0':dict(op='source',path='input.txt')}
    for i in range(1,depth): data['n'+str(i)]=dict(op='sha256',deps=['n'+str(i-1)])
    for i in range(depth,nodes-1): data['n'+str(i)]=dict(op='envcat',deps=['n0'],env=['BUILD','BUILD'],prefix=str(i))
    data['root']=dict(op='sha256',deps=['n'+str(depth-1)]+['n'+str(i) for i in range(depth,nodes-1)],separator='|')
    return dict(nodes=data)


def scenario(task,scale,seed):
    p=parameters(task,scale);rng=random.Random(seed)
    result=dict(task_id=task,scale=scale,seed=seed,parameters=p)
    if task=='C1':
        batches=[]
        for r in range(p['rounds']):
            for t in range(p['tenants']):
                tenant='T'+str(t);events=[]
                for j in range(p['events_per_batch']//4):
                    name=f'p-{r}-{j}';amount=rng.randrange(1,10**9)
                    events.append(ledger_event(tenant,name,amount))
                    # A future reversal is initially ORPHAN then resolves in the next epoch.
                    events.append(dict(tenant=tenant,id=f'r-{r}-{j}',kind='reverse',target=f'p-{r+1}-{j}'))
                    # A delayed different version invalidates an earlier post and its reversal.
                    events.append(ledger_event(tenant,f'p-{r-1}-{j}',amount+1))
                    events.append(dict(tenant=tenant,id=f'bad-{r}-{j}',kind='post',entries=[['cash',True],['equity',-1]]))
                rng.shuffle(events)
                batches.append(dict(tenant=tenant,request_id='epoch-'+str(r),events=events))
        result['batches']=batches
        result['counts']=dict(tenants=p['tenants'],workers=p['workers'],batches=len(batches),
                              events=sum(len(b['events']) for b in batches),http_concurrency=p['http_concurrency'])
    elif task=='C2':
        result['deep_graph']=graph(p['nodes'],p['depth'],3)
        result['revisions']=[dict(project='P'+str(i),revision=r,graph=graph(8,4,seed+r*37+i))
                             for r in range(p['revisions']) for i in range(p['projects'])]
        result['counts']=dict(nodes=len(result['deep_graph']['nodes']),depth=p['depth'],
                              projects=p['projects'],queued_snapshots=len(result['revisions']))
    elif task=='C3':
        result['fault_schedule']=[dict(history=h,cut=cut,mode=mode) for h in range(p['histories'])
                                  for cut in ['commit_write','commit_fsync','compact_write','compact_fsync','replace','dirsync']
                                  for mode in ['before_eio','after_eio','short_enospc','kill_after']]
        result['initial_records']=[['k'+str(i),str(rng.randrange(10**9))] for i in range(p['keys'])]
        result['transactions']=[dict(txid=f'tx-{h}-{j}',ops=[dict(op='put',key=f'k{j%p["keys"]}',value=str(seed+h+j)),
                                                          dict(op='del',key=f'k{(j+1)%p["keys"]}')])
                                for h in range(p['histories']) for j in range(p['transactions'])]
        result['counts']=dict(keys=len(result['initial_records']),fault_histories=len(result['fault_schedule']),
                              transactions=len(result['transactions']),snapshot_readers=p['snapshot_readers'])
    else:
        result['deep_graph']=file_graph(p['nodes'],p['depth'])
        result['histories']=[dict(root=i%p['roots'],payload=f'{seed+i:012d}',env={'BUILD':str(i%17)},
                                 operation=['same_mtime','delete_repair','order_change','publish_retry'][i%4])
                             for i in range(p['mutations'])]
        result['counts']=dict(nodes=len(result['deep_graph']['nodes']),depth=p['depth'],roots=p['roots'],
                              mutations=len(result['histories']),parallel_publishers=p['parallel_publishers'])
    return result


def vector_reference(spec,target):
    """Iterative reference for the generated input/scale/sum/concat graphs."""
    aliases=spec.get('aliases',{});nodes=spec['nodes'];memo={};active=set();stack=[(target,False)]
    while stack:
        name,ready=stack.pop();seen=set()
        while name in aliases:
            if name in seen: raise ValueError('ALIAS_CYCLE')
            seen.add(name);name=aliases[name]
        if name in memo: continue
        if name not in nodes: raise ValueError('MISSING')
        node=nodes[name]
        if not ready:
            if name in active: raise ValueError('CYCLE')
            active.add(name);stack.append((name,True))
            stack.extend((d,False) for d in reversed(node.get('deps',[])));continue
        values=[]
        for d in node.get('deps',[]):
            while d in aliases:d=aliases[d]
            values.append(memo[d])
        op=node['op']
        if op=='input': out=list(node['data'])
        elif op=='scale':out=[v*node['factor'] for vs in values for v in vs]
        elif op=='sum':out=[sum(v[i] if i<len(v) else 0 for v in values) for i in range(max(map(len,values),default=0))]
        elif op=='concat':out=[v for vs in values for v in vs]
        else:raise ValueError(op)
        memo[name]=out;active.remove(name)
    while target in aliases:target=aliases[target]
    return memo[target]


def bytes_reference(spec,target,files,env):
    """No cache, no recursion, no candidate import; filesystem contents passed explicitly."""
    nodes=spec['nodes'];memo={};active=set();stack=[(target,False)]
    while stack:
        name,ready=stack.pop()
        if name in memo:continue
        node=nodes[name]
        if not ready:
            if name in active:raise ValueError('cycle')
            active.add(name);stack.append((name,True));stack.extend((d,False) for d in reversed(node.get('deps',[])));continue
        joined=node.get('separator','').encode().join(memo[d] for d in node.get('deps',[]));op=node['op']
        if op=='source':out=files[node['path']]
        elif op=='sha256':out=hashlib.sha256(joined).hexdigest().encode()
        elif op=='envcat':out=node.get('prefix','').encode()+joined+b''.join(str(env.get(k,'')).encode() for k in node.get('env',[]))
        elif op=='concat':out=joined
        elif op=='upper':out=joined.decode().upper().encode()
        elif op=='reverse':out=joined.decode()[::-1].encode()
        else:raise ValueError(op)
        memo[name]=out;active.remove(name)
    return memo[target]


def tiny_witnesses():
    v=vector_reference(graph(8,4,3),'main')
    assert v==[12,20],v
    s={'nodes':{'s':dict(op='source',path='x'),'e':dict(op='envcat',deps=['s'],env=['A','A'],prefix='!')}}
    b=bytes_reference(s,'e',{'x':b'z'},{'A':'1'})
    assert b==b'!z11'
    return dict(vector_sum=v,byte_env_duplicate=b.decode(),independent=True)
