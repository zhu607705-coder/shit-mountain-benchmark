from __future__ import annotations
import tempfile,json,os,time,subprocess,sys,random,hashlib
from pathlib import Path


def evaluate(mod):
    checks=[]
    def check(name,fn):
        try:fn();checks.append({'name':name,'pass':True})
        except Exception as e:checks.append({'name':name,'pass':False,'error':repr(e)})
    def fixture(d):
        root=Path(d)/'work';root.mkdir();cache=Path(d)/'cache';(root/'a').write_text('alpha');(root/'b').write_text('beta')
        s={'nodes':{'a':{'op':'source','path':'a'},'b':{'op':'source','path':'b'},'x':{'op':'concat','deps':['b','a'],'separator':'|'},'out':{'op':'envcat','deps':['x'],'env':['MODE'],'prefix':'>'}}}
        return root,cache,s
    def existing_ascii():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);s['nodes']['simple']={'op':'upper','deps':['a']}
            assert mod.Builder(root,cache).build(s,'simple')==b'ALPHA'
    def order():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);assert mod.Builder(root,cache).build(s,'out',{'MODE':'dev'})==b'>beta|alphadev'
    def same_size():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);b=mod.Builder(root,cache);b.build(s,'out');p=root/'a';st=p.stat();p.write_text('ALPHA');os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns));assert b.build(s,'out')==b'>beta|ALPHA'
    def transitive():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);b=mod.Builder(root,cache);b.build(s,'out');s['nodes']['x']['separator']='::';assert b.build(s,'out')==b'>beta::alpha'
    def env():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);b=mod.Builder(root,cache);b.build(s,'out',{'MODE':'old'});assert b.build(s,'out',{'MODE':'new'})==b'>beta|alphanew'
    def missing():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);b=mod.Builder(root,cache);b.build(s,'out');(root/'a').unlink()
            try:b.build(s,'out')
            except mod.BuildError:pass
            else:raise AssertionError('deleted source was hidden by cache')
    def cycle():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);s['nodes']['x']['deps']=['out']
            try:mod.Builder(root,cache).build(s,'out')
            except mod.CycleError:pass
            else:raise AssertionError('cycle not diagnosed')
    def irrelevant():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);s['nodes']['unrelated']={'op':'concat','deps':['unrelated']};assert mod.Builder(root,cache).build(s,'out')==b'>beta|alpha'
    def escape():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);(Path(d)/'outside').write_text('secret');(root/'a').unlink();(root/'a').symlink_to(Path(d)/'outside')
            try:mod.Builder(root,cache).build(s,'out')
            except mod.UnsafePath:pass
            else:raise AssertionError('outside-root source read')
    def unicode():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);(root/'a').write_text('甲乙');s['nodes']['x']={'op':'reverse','deps':['a']};assert mod.Builder(root,cache).build(s,'out')=='>乙甲'.encode()
    def roots():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);r2=Path(d)/'other';r2.mkdir();(r2/'a').write_text('gamma');(r2/'b').write_text('delta');mod.Builder(root,cache).build(s,'out');assert mod.Builder(r2,cache).build(s,'out')==b'>delta|gamma'
    def warm():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);mod.Builder(root,cache).build(s,'out');b=mod.Builder(root,cache);assert b.build(s,'out')==b'>beta|alpha'
            # stats is optional untrusted debug output, not a public API gate.
    def corrupt_cache():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);mod.Builder(root,cache).build(s,'out')
            for path in cache.rglob('*'):
                if path.is_file() and not path.is_symlink():path.write_bytes(b'\xff{"incomplete":')
            assert mod.Builder(root,cache).build(s,'out')==b'>beta|alpha'
    def invalid_utf8():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);(root/'a').write_bytes(b'\xff');s['nodes']['out']={'op':'upper','deps':['a']}
            try:mod.Builder(root,cache).build(s,'out')
            except mod.BuildError:pass
            else:raise AssertionError('invalid UTF-8 text operation accepted')
    def changed_cwd():
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as d:
            try:
                root,cache,s=fixture(d);os.chdir(d);b=mod.Builder(root,'cache');b.build(s,'out')
                (Path(d)/'elsewhere').mkdir();os.chdir(Path(d)/'elsewhere')
                assert b.build(s,'out')==b'>beta|alpha'
            finally:os.chdir(previous)
    def concurrent():
        code='''import importlib.util,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).resolve().parent))
s=importlib.util.spec_from_file_location("candidate",sys.argv[1]);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
spec=json.load(open(sys.argv[4]));b=m.Builder(sys.argv[2],sys.argv[3]);assert b.build(spec,"out",{"MODE":"live"})==b">beta|alphalive"
'''
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);sp=Path(d)/'spec.json';sp.write_text(json.dumps(s));ps=[subprocess.Popen([sys.executable,'-c',code,mod.__file__,str(root),str(cache),str(sp)],stderr=subprocess.PIPE) for _ in range(6)]
            try:
                for p in ps:
                    _,err=p.communicate(timeout=10);assert p.returncode==0,err.decode()
            finally:
                for p in ps:
                    if p.poll() is None:p.kill()
                    p.communicate(timeout=5)
    def random_mutations():
        with tempfile.TemporaryDirectory() as d:
            root,cache,s=fixture(d);b=mod.Builder(root,cache);r=random.Random(45)
            for i in range(100):
                a=''.join(r.choices('abcde',k=5));c=''.join(r.choices('vwxyz',k=4));sep=r.choice(['|','-',':']);v=str(r.randrange(5));(root/'a').write_text(a);(root/'b').write_text(c);s['nodes']['x']['separator']=sep
                assert b.build(s,'out',{'MODE':v})==('>'+c+sep+a+v).encode()
    for name,fn in [('existing_ascii_upper_regression',existing_ascii),('dependency_order_and_prefix',order),('same_mtime_same_size_change',same_size),('transitive_recipe_change',transitive),('environment_change',env),('deleted_source',missing),('reachable_cycle',cycle),('irrelevant_cycle',irrelevant),('symlink_escape',escape),('unicode_codepoint_reverse',unicode),('shared_cache_multiple_roots',roots),('warm_cache_reuse',warm),('corrupt_cache_recomputed',corrupt_cache),('invalid_utf8_build_error',invalid_utf8),('relative_cache_after_cwd_change',changed_cwd),('six_process_publish',concurrent),('random_mutations_100',random_mutations)]:check(name,fn)
    with tempfile.TemporaryDirectory() as d:
        root,cache,s=fixture(d);b=mod.Builder(root,cache);t=time.perf_counter();b.build(s,'out');cold=time.perf_counter()-t;t=time.perf_counter()
        for _ in range(100):b.build(s,'out')
        warm_ms=(time.perf_counter()-t)*10
    return {'checks_passed':sum(x['pass'] for x in checks),'checks_total':len(checks),'checks':checks,'cold_ms':cold*1000,'warm_mean_ms_100':warm_ms,'timing_note':'tiny pilot DAG; not the 5000-node tournament workload'}
