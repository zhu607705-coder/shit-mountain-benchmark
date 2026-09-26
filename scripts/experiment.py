#!/usr/bin/env python3
"""Prepare README-driven agent experiments; atomically seal answers; grade privately."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'organizer'))
from efficiency import score_efficiency
TASKS = tuple(f'{track}{i}' for track in 'RCF' for i in range(1,5))
METRICS = ('total_ms','ttft_ms','output_tokens','reasoning_tokens','thinking_time_ms')
LOGICAL_METRICS = ('logical_total_ms','logical_ttft_ms','logical_output_tokens','logical_reasoning_tokens')
METRIC_LABELS = ('measurement_source','latency_source','measurement_scope')
METRIC_LABEL = re.compile(r'^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$')
ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$')
MAX_FILES, MAX_BYTES = 10000, 256*1024*1024


def now(): return datetime.now(timezone.utc).isoformat()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path, value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def load(path):
    def pairs(items):
        obj={}
        for k,v in items:
            if k in obj: raise ValueError('duplicate JSON key: '+k)
            obj[k]=v
        return obj
    def invalid(value): raise ValueError('non-finite JSON: '+value)
    return json.loads(Path(path).read_text(),object_pairs_hook=pairs,parse_constant=invalid)
def identifier(value):
    if type(value) is not str or not ID.fullmatch(value): raise ValueError('invalid identifier')
    return value


def inventory(directory):
    directory=Path(directory)
    if directory.is_symlink(): raise ValueError('symlink directory refused')
    rows=[]; total=0
    for p in sorted(directory.rglob('*')):
        info=p.lstat()
        if stat.S_ISLNK(info.st_mode): raise ValueError('symlinks are not accepted: '+str(p))
        if stat.S_ISDIR(info.st_mode): continue
        if not stat.S_ISREG(info.st_mode): raise ValueError('only regular files and directories accepted')
        total+=info.st_size
        if len(rows)>=MAX_FILES or total>MAX_BYTES: raise ValueError('submission exceeds 10000 files / 256 MiB')
        rows.append({'path':p.relative_to(directory).as_posix(),'bytes':info.st_size,'sha256':sha(p),'executable':bool(info.st_mode & 0o111)})
    return rows


def readonly(directory):
    for p in sorted(Path(directory).rglob('*'),reverse=True):
        p.chmod(0o555 if p.is_dir() or p.stat().st_mode & 0o111 else 0o444)
    Path(directory).chmod(0o555)


def relative_entry(payload,value):
    if type(value) is not str or not value or '\\' in value: raise ValueError('entrypoint must be a relative POSIX path')
    rel=PurePosixPath(value)
    if rel.is_absolute() or '..' in rel.parts: raise ValueError('entrypoint escapes the payload')
    target=(Path(payload)/value).resolve(strict=True)
    if not target.is_relative_to(Path(payload).resolve()): raise ValueError('entrypoint escapes the payload')
    return value


def validate_plan(plan):
    if type(plan) is not dict: raise ValueError('plan must be object')
    identifier(plan['id'])
    if plan['id'].casefold()=='cohorts': raise ValueError('cohorts is reserved for private comparison groups')
    if 'cohort_id' in plan: identifier(plan['cohort_id'])
    tasks=plan.get('tasks')
    if type(tasks) is not list or not tasks or len(tasks)!=len(set(tasks)) or any(x not in TASKS for x in tasks):
        raise ValueError('tasks must contain distinct R1-R4/C1-C4/F1-F4 IDs')
    variants=plan.get('prompt_variants')
    if type(variants) is not list or not 1<=len(variants)<=10: raise ValueError('1..10 prompt variants required')
    ids=[]
    for variant in variants:
        if type(variant) is not dict or set(variant)!={'id','text'}: raise ValueError('variant requires exactly id/text')
        ids.append(identifier(variant['id']))
        if len(variant['id'])>64: raise ValueError('variant id must be at most 64 characters')
        if type(variant['text']) is not str or not variant['text'].strip(): raise ValueError('empty prompt variant')
    if len(ids)!=len(set(ids)): raise ValueError('duplicate variant id')
    if type(plan.get('rounds')) is not int or not 1<=plan['rounds']<=100: raise ValueError('rounds must be 1..100')
    if plan.get('scale') not in ('smoke','full'): raise ValueError('scale must be smoke/full')
    budgets=plan.get('budgets',{})
    if type(budgets) is not dict or set(budgets)-set(METRICS): raise ValueError('unknown budget metric')
    for key,value in budgets.items():
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<=0):
            raise ValueError('budget must be a positive number or null: '+key)
    if 'efficiency_policy' in plan:
        policy=plan['efficiency_policy']
        if type(policy) is not dict or set(policy)!={'profile','budgets'}: raise ValueError('efficiency_policy requires profile and budgets')
        score_efficiency(None,None,{},policy['budgets'],profile=policy['profile'])
    return plan


def metrics_record(path):
    source=load(path) if path else {}
    if type(source) is not dict: raise ValueError('metrics must be an object')
    out={key:source.get(key) for key in METRICS}
    # Absence and explicit null are different: an absent cumulative field may
    # use the legacy single-attempt value; an unknown retry total must stay null.
    out.update({key:source[key] for key in LOGICAL_METRICS if key in source})
    for key,value in out.items():
        if value is None: continue
        if type(value) not in (int,float) or not math.isfinite(value) or value<0: raise ValueError('invalid metric: '+key)
        if key.endswith('_tokens') and type(value) is not int: raise ValueError('token counts must be integers')
    if out['ttft_ms'] is not None and out['total_ms'] is not None and out['ttft_ms']>out['total_ms']:
        raise ValueError('ttft_ms cannot exceed total_ms')
    if (out.get('logical_ttft_ms') is not None and out.get('logical_total_ms') is not None and
            out['logical_ttft_ms']>out['logical_total_ms']):
        raise ValueError('logical_ttft_ms cannot exceed logical_total_ms')
    for total,current in [('logical_total_ms','total_ms'),('logical_output_tokens','output_tokens'),
                          ('logical_reasoning_tokens','reasoning_tokens')]:
        if out.get(total) is not None and out[current] is not None and out[total]<out[current]:
            raise ValueError(total+' cannot be smaller than the recorded attempt value')
    for key in ('simulated','logical_final'):
        if key in source:
            if type(source[key]) is not bool: raise ValueError(key+' must be a boolean')
            out[key]=source[key]
    for key in METRIC_LABELS:
        if key in source:
            value=source[key]
            if value is not None and (type(value) is not str or not METRIC_LABEL.fullmatch(value)):
                raise ValueError(key+' must be a bounded machine-readable label or null')
            out[key]=value
    claimed=source.get('source','agent_self_reported')
    if claimed not in ('agent_self_reported','host','API'): raise ValueError('unknown metric source')
    out.update(source=claimed,trust='unverified',efficiency_eligible=False,
               trust_reason='Source labels are claims. Codex must inspect independent host/API evidence before efficiency scoring.')
    evidence=source.get('evidence_files',[])
    if type(evidence) is not list or any(type(p) is not str for p in evidence): raise ValueError('evidence_files must be relative paths')
    out['evidence_files']=evidence
    return out


def private_path(experiment_id): return ROOT/'reports'/'experiments'/identifier(experiment_id)


def context(workspace):
    workspace=Path(workspace).resolve(strict=True)
    public=load(workspace/'experiment.json')
    private=private_path(public['id'])
    record=load(private/'organizer.json')
    if Path(record['workspace'])!=workspace: raise ValueError('workspace does not match organizer record')
    return workspace,private,record


def run(command, *, timeout=180):
    p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=timeout)
    if p.returncode: raise RuntimeError(f'command exited {p.returncode}: {p.stderr[-2500:]}\n{p.stdout[-1000:]}')
    return {'command':command,'exit_code':p.returncode,'stdout':p.stdout[-4000:],'stderr':p.stderr[-4000:]}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def generator_fingerprints(tasks):
    files={ROOT/'scripts'/'extreme.py',ROOT/'organizer'/'extreme_contract.py'}
    for task in tasks:
        track={'R':'reasoning','C':'code','F':'frontend'}[task[0]]
        folder=ROOT/track
        files.update(folder.glob('extreme*.py'))
        files.update((folder/task).rglob('*.py'))
        files.update((folder/task/'extreme').glob('*.md'))
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files) if p.is_file()}


def comparison_record(plan,task_hashes,frozen_efficiency):
    design={key:plan[key] for key in ('tasks','rounds','prompt_variants','scale')}
    design.update(budgets=plan.get('budgets',{}),efficiency_policy=frozen_efficiency,
                  public_task_hashes=task_hashes,generator_fingerprints=generator_fingerprints(plan['tasks']))
    def fresh():
        seeds={task:{str(r):secrets.randbits(63) for r in range(1,plan['rounds']+1)} for task in plan['tasks']}
        return {'design':design,'seeds':seeds,'comparison_id':canonical_hash({'design':design,'seeds':seeds})}
    if 'cohort_id' not in plan:return fresh()
    folder=ROOT/'reports'/'experiments'/'cohorts';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(plan['cohort_id']+'.json');lock=folder/(plan['cohort_id']+'.lock')
    try:fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:raise ValueError('cohort is locked; another prepare is in progress') from None
    temporary=None
    try:
        os.close(fd)
        if path.exists():
            if path.is_symlink():raise ValueError('cohort record must be a regular private file')
            saved=load(path)
            if saved.get('design')!=design:raise ValueError('cohort design/generator differs; use a new cohort_id')
            if saved.get('comparison_id')!=canonical_hash({'design':design,'seeds':saved['seeds']}):
                raise ValueError('cohort comparison fingerprint is inconsistent')
            return saved
        saved=fresh();saved['cohort_id']=plan['cohort_id']
        fd,name=tempfile.mkstemp(prefix='.'+plan['cohort_id']+'-',suffix='.tmp',dir=folder)
        temporary=Path(name)
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(saved,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path);temporary=None
        return saved
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def control_paths(assignments,has_efficiency):
    paths=['README.md','experiment.json','assignments.json']
    paths.extend('answers/'+item['attempt_id']+'/README.md' for item in assignments)
    if has_efficiency:paths.append('efficiency-budgets.json')
    return sorted(paths)


def check_controls(workspace,record):
    expected=record.get('control_hashes')
    required=control_paths(record['assignments'],record.get('efficiency_policy') is not None)
    if type(expected) is not dict or set(expected)!=set(required):
        return {'ok':False,'frozen':False,'status':'not_frozen','files':{}}
    observed={}
    for name,digest in expected.items():
        try:observed[name]=sha(checked_child(workspace,workspace/name))==digest
        except (OSError,ValueError):observed[name]=False
    okay=all(observed.values())
    return {'ok':okay,'frozen':True,'status':'frozen' if okay else 'changed','files':observed}


def require_controls(state):
    if not state['control_integrity']['ok']:
        raise ValueError('experiment controls changed or were not frozen; create a fresh experiment')
    if state.get('generator_integrity') is not True:
        raise ValueError('frozen task generator sources changed; use the original revision or a fresh experiment')


def prepare(plan_path, output, *, exporter=None):
    plan=validate_plan(load(plan_path))
    workspace=Path(output).resolve()
    private=private_path(plan['id'])
    if workspace.exists() or private.exists(): raise ValueError('workspace or organizer experiment already exists; choose a fresh id/path')
    workspace.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.'+workspace.name+'-',dir=workspace.parent))
    private.mkdir(parents=True)
    assignments=[]
    try:
        task_hashes={}
        for task in plan['tasks']:
            destination=stage/'tasks'/task
            if exporter:
                exporter(task,plan['scale'],destination)
            else:
                track={'R':'reasoning','C':'code','F':'frontend'}[task[0]]
                # Public fixtures and private grading seeds are deliberately different.
                run([sys.executable,str(ROOT/track/'extreme.py'),'--task',task,'--scale',plan['scale'],
                     '--seed','260926','--export',str(destination),'--output',str(private/f'export-{task}.json')],timeout=300)
            task_hashes[task]=inventory(destination)
            readonly(destination)
        for task in plan['tasks']:
            for variant in plan['prompt_variants']:
                for round_id in range(1,plan['rounds']+1):
                    aid=f'{task}-{variant["id"]}-r{round_id:02d}'
                    item={'attempt_id':aid,'task':task,'variant':variant['id'],'round':round_id,
                          'shared_task':f'tasks/{task}','answer_directory':f'answers/{aid}',
                          'prompt':variant['text'],'budgets':plan.get('budgets',{})}
                    assignments.append(item)
                    folder=stage/'answers'/aid
                    folder.mkdir(parents=True)
                    (folder/'README.md').write_text(f'''# Attempt {aid}

Start a new independent Agent session for this attempt. Read `../../tasks/{task}/PROMPT.md` first.

{variant['text']}

Shared input: `../../tasks/{task}/` (read only). Create your working copy under `work/` in this attempt directory; do not edit another attempt or inspect private organizer files. Do not copy all inputs 108 times in advance; make a copy only when starting this attempt.

Budget declaration: `{json.dumps(plan.get('budgets',{}),ensure_ascii=False)}`. The host must enforce experiment budgets; this README does not enforce model API budgets.

The organizer can create an editable copy with `scripts/experiment.py start --workspace <workspace> --attempt {aid}`; this copy helper does not launch a model or measure its thinking time. Alternatively copy the public files yourself and make only your own work copy writable.

Deposit your solution, a short method/change summary, reproduction commands and self-test evidence in `work/`. Report unobservable token/time fields as null; TTFT is not internal thinking time. Do not provide private chain-of-thought. The organizer seals the answer with `scripts/experiment.py submit`, then Codex independently grades it. Agent self-reported success is not a grade.
''')
        public={k:plan[k] for k in ('id','tasks','prompt_variants','rounds','scale')}
        public.update(budgets=plan.get('budgets',{}),attempts=len(assignments),created_at=now())
        frozen_efficiency=None
        if 'efficiency_policy' in plan:
            cfg=plan['efficiency_policy']
            assessed=score_efficiency(None,None,{},cfg['budgets'],profile=cfg['profile'])
            frozen_efficiency={'policy':assessed['policy'],'score_profile_id':assessed['score_profile_id']}
            public['efficiency_policy']=frozen_efficiency
            write(stage/'efficiency-budgets.json',assessed['policy']['budgets'])
        comparison=comparison_record(plan,task_hashes,frozen_efficiency)
        public['comparison_id']=comparison['comparison_id']
        if 'cohort_id' in plan:public['cohort_id']=plan['cohort_id']
        write(stage/'experiment.json',public)
        write(stage/'assignments.json',assignments)
        (stage/'README.md').write_text(f'''# Agent experiment: {plan['id']}

There are {len(assignments)} independent attempts: {len(plan['tasks'])} tasks × {len(plan['prompt_variants'])} prompt variants × {plan['rounds']} rounds. Read `assignments.json`, select exactly one attempt, then read its `answers/<attempt-id>/README.md` and the shared task's `PROMPT.md`.

1. Start a fresh session for each assigned attempt. If asked to coordinate the whole experiment, dispatch every preregistered attempt into its own fresh session; do not reuse prior answers or claim independence from one continuous context. Read the assignment and copy only its necessary public starter into `work/`.
2. Implement a solution, run relevant self-tests, and save actual files and evidence. The final chat reply alone is not a submission.
3. Record total_ms, ttft_ms, output_tokens, reasoning_tokens and thinking_time_ms only when observed; otherwise null. Include host/API logs when available, never API keys.
4. The organizer uses `submit` to atomically seal the files. Existing sealed answers are immutable and cannot be overwritten.
5. A separate Codex grading pass calls the real task runner on the sealed submission. UI/visual assessment for frontend remains separately pending.

Do not read the organizer reports, hidden seeds or judges. Inputs are shared read-only; each attempt has an independent working directory. The organizer instructions are in repository `experiments/GRADER_README.md`, outside this public bundle.
''')
        record={'id':plan['id'],'workspace':str(workspace),'plan':plan,'assignments':assignments,
                'task_hashes':task_hashes,'created_at':now(),
                'efficiency_policy':frozen_efficiency,
                'seeds':comparison['seeds'],'comparison_id':comparison['comparison_id'],
                'cohort_id':plan.get('cohort_id'),
                'generator_fingerprints':comparison['design']['generator_fingerprints'],
                'control_hashes':{name:sha(stage/name) for name in control_paths(assignments,frozen_efficiency is not None)}}
        write(private/'organizer.json',record)
        os.rename(stage,workspace)
        return {'workspace':str(workspace),'attempts':len(assignments),'private_record':str(private/'organizer.json'),
                'comparison_id':comparison['comparison_id'],'cohort_id':plan.get('cohort_id')}
    except BaseException:
        for p in stage.rglob('*'):
            if p.is_dir(): p.chmod(0o755)
        shutil.rmtree(stage,ignore_errors=True)
        shutil.rmtree(private,ignore_errors=True)
        raise


def assignment(record, attempt):
    identifier(attempt)
    result=next((a for a in record['assignments'] if a['attempt_id']==attempt),None)
    if result is None: raise ValueError('unknown attempt')
    return result


def checked_child(workspace,path):
    workspace=Path(workspace).resolve();path=Path(path)
    try: parts=path.relative_to(workspace).parts
    except ValueError: raise ValueError('workspace destination escapes its root')
    current=workspace
    for part in parts:
        current=current/part
        if current.is_symlink(): raise ValueError('workspace destination contains a symlink')
    if not path.resolve().is_relative_to(workspace): raise ValueError('workspace destination escapes its root')
    return path


def start(workspace,attempt):
    workspace,private,record=context(workspace)
    item=assignment(record,attempt)
    state=inspect(workspace)
    require_controls(state)
    if not state['task_input_integrity'][item['task']]: raise ValueError('shared input changed')
    parent=checked_child(workspace,workspace/'answers'/attempt)
    if (parent/'sealed').exists(): raise ValueError('attempt is already sealed')
    work=parent/'work'
    if work.exists(): raise ValueError('working copy already exists; refusing overwrite')
    stage=Path(tempfile.mkdtemp(prefix='.work-',dir=parent))
    try:
        shutil.copytree(workspace/'tasks'/item['task'],stage,dirs_exist_ok=True)
        for p in stage.rglob('*'):
            p.chmod(0o755 if p.is_dir() or p.stat().st_mode & 0o111 else 0o644)
        stage.chmod(0o755)
        if work.exists() or work.is_symlink(): raise ValueError('working copy appeared; refusing overwrite')
        os.rename(stage,work)
    finally:
        if stage.exists():
            for p in stage.rglob('*'):
                if p.is_dir(): p.chmod(0o755)
            stage.chmod(0o755);shutil.rmtree(stage)
    write(private/f'work-start-{attempt}.json',{'attempt_id':attempt,'created_at':now(),'measurement_trust':'unverified_start_helper_not_a_model_timer'})
    return {'attempt_id':attempt,'work':str(work),'model_launched':False,'timing_verified':False}


def submit(workspace,attempt,source,metrics=None,entrypoint=None):
    workspace,private,record=context(workspace)
    item=assignment(record,attempt)
    state=inspect(workspace);require_controls(state)
    if not state['task_input_integrity'][item['task']]:raise ValueError('shared input changed')
    folder=checked_child(workspace,workspace/'answers'/attempt)
    sealed=folder/'sealed'
    receipt=private/'receipts'/f'{attempt}.json'
    source=Path(source).absolute()
    if source.is_symlink(): raise ValueError('source symlink refused')
    source=source.resolve(strict=True)
    if source.is_dir() and sealed.resolve().is_relative_to(source): raise ValueError('source contains its own destination')
    lock=folder/'.submit.lock'
    fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    stage=None
    try:
        os.close(fd)
        if sealed.exists() or receipt.exists(): raise ValueError('attempt already sealed or reserved; overwrites are prohibited')
        stage=Path(tempfile.mkdtemp(prefix='.import-',dir=folder))
        payload=stage/'payload'
        if source.is_dir():
            inventory(source)
            shutil.copytree(source,payload,symlinks=False)
            if entrypoint is None: raise ValueError('directory submission requires --entrypoint, e.g. . or policy.py')
        else:
            if not source.is_file(): raise ValueError('source must be regular file or directory')
            if source.stat().st_size>MAX_BYTES: raise ValueError('source file exceeds 256 MiB')
            payload.mkdir()
            shutil.copy2(source,payload/source.name)
            if entrypoint is None: entrypoint=source.name
        relative_entry(payload,entrypoint)
        met=metrics_record(metrics)
        for evidence in met['evidence_files']: relative_entry(payload,evidence)
        write(stage/'metrics.json',met)
        files=inventory(stage)
        manifest={'version':1,'attempt_id':attempt,'task':item['task'],'entrypoint':entrypoint,
                  'submitted_at':now(),'source':str(source),'files':files}
        write(stage/'manifest.json',manifest)
        receipt.parent.mkdir(parents=True,exist_ok=True)
        anchor={'attempt_id':attempt,'manifest_sha256':sha(stage/'manifest.json'),'sealed_at':now()}
        with receipt.open('x') as f: json.dump(anchor,f,ensure_ascii=False,indent=2)
        try:
            os.rename(stage,sealed)
            stage=None
        except BaseException:
            receipt.unlink(missing_ok=True)
            raise
        readonly(sealed)
        return {'attempt_id':attempt,'status':'sealed','files':len(files),'manifest_sha256':anchor['manifest_sha256'],
                'sealed':str(sealed),'metrics_trust':'unverified','efficiency_eligible':False}
    finally:
        if stage: shutil.rmtree(stage,ignore_errors=True)
        lock.unlink(missing_ok=True)


def inspect(workspace):
    workspace,private,record=context(workspace)
    inputs={}
    for task,expected in record['task_hashes'].items():
        try: inputs[task]=inventory(checked_child(workspace,workspace/'tasks'/task))==expected
        except (OSError,ValueError): inputs[task]=False
    rows=[]
    for item in record['assignments']:
        aid=item['attempt_id']; sealed=workspace/'answers'/aid/'sealed'; receipt=private/'receipts'/f'{aid}.json'
        row={'attempt_id':aid,'task':item['task'],'variant':item['variant'],'round':item['round'],
             'status':'missing','quality_score':0,'quality_status':'missing_submission'}
        try: checked_child(workspace,sealed)
        except ValueError as exc:
            row.update(status='tampered',error=str(exc),quality_status='integrity_failure');rows.append(row);continue
        if sealed.exists() or receipt.exists():
            try:
                anchor=load(receipt)
                if sha(sealed/'manifest.json')!=anchor['manifest_sha256']: raise ValueError('manifest does not match private receipt')
                manifest=load(sealed/'manifest.json')
                actual=[x for x in inventory(sealed) if x['path']!='manifest.json']
                if actual!=manifest['files']: raise ValueError('file list, length or SHA-256 differs')
                if manifest['attempt_id']!=aid or manifest['task']!=item['task']: raise ValueError('manifest identity differs')
                relative_entry(sealed/'payload',manifest['entrypoint'])
                row.update(status='sealed',manifest_sha256=anchor['manifest_sha256'],quality_score=None,quality_status='grading_pending')
            except (OSError,ValueError,KeyError) as exc: row.update(status='tampered',error=str(exc),quality_score=0,quality_status='integrity_failure')
        rows.append(row)
    controls=check_controls(workspace,record)
    generators=(type(record.get('generator_fingerprints')) is dict and
                generator_fingerprints(record['plan']['tasks'])==record['generator_fingerprints'])
    return {'id':record['id'],'task_input_integrity':inputs,'control_integrity':controls,'attempts':rows,
            'generator_integrity':generators,'comparison_id':record.get('comparison_id'),
            'counts':{state:sum(x['status']==state for x in rows) for state in ('missing','sealed','tampered')},
            'integrity_ok':controls['ok'] and generators and all(inputs.values()) and all(x['status']!='tampered' for x in rows)}


def grade(workspace,attempt,entrypoint=None,timeout=300,*,runner=None):
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0: raise ValueError('timeout must be positive and finite')
    workspace,private,record=context(workspace)
    item=assignment(record,attempt)
    state=inspect(workspace)
    require_controls(state)
    check=next(x for x in state['attempts'] if x['attempt_id']==attempt)
    if check['status']!='sealed' or not state['task_input_integrity'][item['task']]:
        raise ValueError('cannot grade missing/tampered submission or altered shared inputs')
    sealed=workspace/'answers'/attempt/'sealed'
    manifest=load(sealed/'manifest.json')
    entrypoint=relative_entry(sealed/'payload',entrypoint or manifest['entrypoint'])
    # Each grading run gets a fresh private copy: execution cannot mutate the sealed answer.
    grade_id=now().replace(':','').replace('.','')+'-'+secrets.token_hex(3)
    destination=private/'results'/attempt/grade_id
    destination.mkdir(parents=True)
    evaluation=destination/'evaluation-copy'
    shutil.copytree(sealed/'payload',evaluation)
    for p in evaluation.rglob('*'): p.chmod(0o755 if p.is_dir() or p.stat().st_mode & 0o111 else 0o644)
    evaluation.chmod(0o755)
    candidate=evaluation/entrypoint
    seed=record['seeds'][item['task']][str(item['round'])]
    output=destination/'judge'
    command=[sys.executable,str(ROOT/'scripts'/'extreme.py'),'--task',item['task'],
             '--scale',record['plan']['scale'],'--seed',str(seed),'--submission',str(candidate),
             '--output',str(output),'--timeout',str(timeout)]
    try:
        execution=(runner or run)(command,timeout=timeout+30)
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        failure={'experiment_id':record['id'],'attempt_id':attempt,'task':item['task'],
                 'status':'runner_error','quality_score':None,'candidate_result':None,
                 'error':str(exc),'command':command,'scheduled_attempts':state['attempts'],
                 'metrics_trust':'unverified','efficiency_eligible':False}
        write(destination/'grade.json',failure)
        return {'grade':str(destination/'grade.json'),**failure}
    judged=load(output/f'{item["task"]}.json')
    candidate_result=judged.get('candidate_result')
    if judged.get('task_id')!=item['task'] or judged.get('seed')!=seed or candidate_result is None:
        raise ValueError('judge result missing, unrelated or baseline-only')
    after=inspect(workspace)
    require_controls(after)
    if (next(x for x in after['attempts'] if x['attempt_id']==attempt)['status']!='sealed' or
            not after['task_input_integrity'][item['task']]):
        raise ValueError('sealed answer was changed during evaluation')
    is_frontend=item['task'].startswith('F')
    automatic_score=candidate_result.get('semantic_score') if is_frontend else candidate_result.get('raw_score')
    if automatic_score is not None and (type(automatic_score) not in (int,float) or not math.isfinite(automatic_score) or automatic_score<0):
        raise ValueError('judge quality score must be a finite nonnegative number')
    quality={'valid':candidate_result.get('valid'),
             'raw_score':0 if candidate_result.get('valid') is False else automatic_score,
             'scope':'semantic_only' if is_frontend else 'automatic_task_quality',
             'judge_report_sha256':sha(output/f'{item["task"]}.json')}
    if is_frontend:
        quality.update(frontend_visual_review='pending',complete_frontend_status='pending',complete_frontend_score=None)
    write(destination/'quality.json',quality)
    scheduled=after['attempts']
    for planned in scheduled:
        if planned['attempt_id']==attempt:
            planned.update(quality_score=quality['raw_score'],quality_status='graded')
    result={'experiment_id':record['id'],'attempt_id':attempt,'task':item['task'],
            'variant':item['variant'],'round':item['round'],'graded_at':now(),
            'manifest_sha256':check['manifest_sha256'],'entrypoint':entrypoint,
            'judge_report':str(output/f'{item["task"]}.json'),'judge_sha256':sha(output/f'{item["task"]}.json'),
            'audit_passed':judged.get('audit_passed'), 'candidate_result':candidate_result,
            'quality_artifact':str(destination/'quality.json'),'scheduled_attempts':scheduled,
            'metrics':load(sealed/'metrics.json'),'metrics_trust':'unverified','efficiency_eligible':False,
            'frontend_visual_review':'pending' if item['task'].startswith('F') else 'not_applicable',
            'frontend_score_scope':'semantic_only' if item['task'].startswith('F') else None,
            'execution':execution}
    write(destination/'grade.json',result)
    return {'grade':str(destination/'grade.json'),'task':item['task'],'candidate_result':candidate_result,
            'frontend_visual_review':result['frontend_visual_review'],'efficiency_eligible':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare');p.add_argument('--plan',required=True);p.add_argument('--output',required=True)
    p=commands.add_parser('start');p.add_argument('--workspace',required=True);p.add_argument('--attempt',required=True)
    p=commands.add_parser('submit');p.add_argument('--workspace',required=True);p.add_argument('--attempt',required=True)
    p.add_argument('--source',required=True);p.add_argument('--metrics');p.add_argument('--entrypoint')
    p=commands.add_parser('inspect');p.add_argument('--workspace',required=True)
    p=commands.add_parser('grade');p.add_argument('--workspace',required=True);p.add_argument('--attempt',required=True)
    p.add_argument('--entrypoint');p.add_argument('--timeout',type=float,default=300)
    args=vars(parser.parse_args());command=args.pop('command')
    if command=='prepare': args['plan_path']=args.pop('plan')
    try:
        result=globals()[command](**args)
    except (OSError,ValueError,RuntimeError,KeyError,subprocess.TimeoutExpired) as exc:
        parser.exit(2,'experiment: '+str(exc)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    if command=='inspect' and not result['integrity_ok']: return 2
    return 0


if __name__=='__main__': raise SystemExit(main())
