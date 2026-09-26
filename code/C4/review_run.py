#!/usr/bin/env python3
"""Audit runner; writes fresh measurements only when --output is supplied."""
import argparse,importlib.util,json,os,sys,time,platform,hashlib,datetime
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
TASK=HERE.name
IS_STORE=(HERE/"starter"/"store.py").exists()

def load(name,path):
    sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--implementation',choices=['baseline','starter'],default='baseline');parser.add_argument('--output');parser.add_argument('--evaluator')
    args=parser.parse_args();os.environ['PYTHONDONTWRITEBYTECODE']='1'
    path=HERE/('baseline.py' if args.implementation=='baseline' else 'starter/'+('store.py' if IS_STORE else 'engine.py'))
    evaluator_path=Path(args.evaluator).resolve() if args.evaluator else (HERE/'evaluator.py' if (HERE/'evaluator.py').exists() else ROOT/'organizer'/('c1.py' if IS_STORE else 'c2.py'))
    evaluator=load('review_evaluator',evaluator_path)
    candidate=load('review_candidate',path);started=time.perf_counter()
    result=evaluator.evaluate(candidate)
    result.update({'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'measured_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'review_origin':'current independent local execution, not upstream bundled claim','implementation':args.implementation,'task':TASK,'wall_seconds':time.perf_counter()-started,'python':platform.python_version(),'platform':platform.platform()})
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:
        output=Path(__file__).parent/args.output;output.parent.mkdir(parents=True,exist_ok=True);output.write_text(text+'\n')
    print(text)
if __name__=='__main__':main()
