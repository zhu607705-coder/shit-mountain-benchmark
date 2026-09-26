"""Organizer smoke validation. Not an untrusted-submission sandbox."""
import argparse,importlib.util,json,sys,time,platform,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--task',choices=['R1','R2','C1','C2','all'],default='all');a=p.parse_args()
    tasks={'R1':'R1_diagnosis','R2':'R2_dispatch','C1':'C1_crashkv','C2':'C2_cache'}
    (ROOT/'results').mkdir(exist_ok=True)
    for task,folder in tasks.items():
        if a.task not in ('all',task):continue
        policy=load(task+'_baseline',ROOT/'tasks'/folder/'baseline.py');evaluator=load(task+'_eval',ROOT/'organizer'/f'{task.lower()}.py')
        t=time.time();result=evaluator.evaluate(policy);result['elapsed_seconds']=time.time()-t;result['python']=sys.version;result['platform']=platform.platform()
        (ROOT/'results'/f'{task}_baseline.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(task,{k:v for k,v in result.items() if k not in ('checks','episodes_detail')},flush=True)
