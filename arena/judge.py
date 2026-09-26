"""Scope-aware Arena wrapper around real repository judges; never grades chat claims."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from arena.rules import validate_private
from organizer.efficiency import score_efficiency


def _number(value):return type(value) in (int,float) and math.isfinite(value)
def _tail(values):
    remaining=len(values)*.1;mass=remaining;total=0.
    for value in sorted(values,reverse=True):
        take=min(1.,remaining);total+=take*value;remaining-=take
        if remaining<1e-12:break
    return total/mass


def score_report(report,spec):
    """Select only the published scope. Extra diagnostic failures do not count."""
    if report.get('audit_passed') is not True:raise ValueError('judge audit did not pass')
    candidate=report.get('candidate_result')
    if type(candidate) is not dict:raise ValueError('candidate result missing; baseline is not a submission grade')
    scope=spec['scope'];task=spec['task_id']
    if task.startswith('R'):
        rows=candidate.get('episodes_detail')
        if type(rows) is not list or not rows:raise ValueError('reasoning episode evidence missing')
        limit=scope['episode_limit'];selected=rows[:limit] if limit else rows
        if any(type(r.get('valid')) is not bool or not _number(r.get('loss')) or r['loss']<0 for r in selected):
            raise ValueError('reasoning episode evidence malformed')
        scale=candidate.get('loss_scale')
        if not _number(scale) or scale<=0:raise ValueError('reasoning loss scale missing')
        valid=all(r['valid'] for r in selected);losses=[r['loss'] for r in selected]
        objective=.7*statistics.fmean(losses)+.3*_tail(losses)
        return {'valid':valid,'legal':valid,'completed':valid,'raw_score':100/(1+objective/scale) if valid else 0,
                'selected_checks':[{'name':f'episode_{i+1}_legal','passed':r['valid'],'loss':r['loss']} for i,r in enumerate(selected)],
                'objective_loss':objective,'selected_count':len(selected),
                'available_count':len(rows),'failures':[f'episode {i+1}: '+str(r.get('error','illegal action')) for i,r in enumerate(selected) if not r['valid']],
                'summary':f'{sum(r["valid"] for r in selected)}/{len(selected)} selected episodes legal; quality remains continuous'}
    checks=candidate.get('checks')
    if type(checks) is not list or not checks:raise ValueError('check evidence missing')
    if any(type(c) is not dict or type(c.get('name')) is not str or type(c.get('passed')) is not bool for c in checks):
        raise ValueError('check evidence malformed')
    selector=scope['selector'];missing=[]
    if selector['mode']=='all':selected=checks[:]
    else:
        names=set(selector['names']);patterns=[re.compile(p) for p in selector.get('patterns',[])]
        selected=[c for c in checks if c['name'] in names or any(p.fullmatch(c['name']) for p in patterns)]
        missing=sorted(names-{c['name'] for c in selected})
        matches=sum(any(p.fullmatch(c['name']) for p in patterns) for c in checks)
        if matches<selector.get('minimum_pattern_matches',0):missing.append('published fault family incomplete')
    for name in missing:selected.append({'name':name,'passed':False,'detail':'required selected check absent'})
    if scope['require_stage_v2'] and not any(c['name'].startswith('stage_v2_') for c in selected):
        selected.append({'name':'stage_v2_capability','passed':False,'detail':'required stage evidence absent'})
    if not selected:raise ValueError('no checks matched public scope')
    valid=all(c['passed'] for c in selected)
    if selector['mode']=='all' and candidate.get('valid') is not True:
        valid=False
    passed=sum(c['passed'] for c in selected)
    failures=[c['name']+': '+str(c.get('detail') or c.get('error') or 'failed') for c in selected if not c['passed']]
    if not valid and not failures:failures.append('full candidate protocol/exit validity failed')
    foundations=set(scope.get('foundation_checks',[]))
    severe=any((c['name'] in foundations or c['name']=='stage_v2_capability') and not c['passed'] for c in selected)
    if selector['mode']=='all' and not valid and not any(not c['passed'] for c in selected):severe=True
    if selector['mode']=='all' and candidate.get('failure'):severe=True
    if selector['mode']=='all' and report.get('verification',{}).get('adapter_acknowledged',{}).get('protocol_errors'):severe=True
    quality=0 if severe else 100*passed/len(selected)
    return {'valid':not severe,'legal':not severe,'completed':valid,'raw_score':quality,'selected_checks':selected,'selected_count':len(selected),
            'available_count':len(checks),'failures':failures,
            'summary':f'{passed}/{len(selected)} selected checks passed',
            'score_scope':'semantic_only' if task.startswith('F') else 'machine_contract',
            'severe_foundation_failure':severe}


def _descendants(pid):
    """Include workers that create their own sessions; process groups alone miss them."""
    try:
        result=subprocess.run(['ps','-axo','pid=,ppid='],capture_output=True,text=True,timeout=3)
        parents={int(line.split()[0]):int(line.split()[1]) for line in result.stdout.splitlines() if len(line.split())==2}
    except (OSError,ValueError,subprocess.TimeoutExpired):return {pid}
    found={pid}
    while True:
        children={child for child,parent in parents.items() if parent in found}
        if children.issubset(found):break
        found|=children
    return found


def _stop(process):
    pids=_descendants(process.pid)
    for sig in (signal.SIGTERM,signal.SIGKILL):
        for pid in sorted(pids,reverse=True):
            try:
                group=os.getpgid(pid)
                if group==pid and group!=os.getpgrp():os.killpg(group,sig)
                else:os.kill(pid,sig)
            except ProcessLookupError:pass
        try:process.wait(timeout=.4)
        except subprocess.TimeoutExpired:pass
    try:process.wait(timeout=2)
    except subprocess.TimeoutExpired:pass


def _run(command,directory,timeout,cancel_event=None,progress=None,case_index=1,case_count=1):
    started=time.monotonic()
    with (directory/'stdout.log').open('w') as out,(directory/'stderr.log').open('w') as err:
        process=subprocess.Popen(command,cwd=ROOT,stdout=out,stderr=err,start_new_session=True)
        last=-1
        try:
            while process.poll() is None:
                elapsed=time.monotonic()-started
                if cancel_event is not None and cancel_event.is_set():
                    _stop(process);return {'status':'cancelled','exit_code':process.returncode,'elapsed_seconds':elapsed}
                if elapsed>timeout:
                    _stop(process);return {'status':'runner_timeout','exit_code':process.returncode,'elapsed_seconds':elapsed}
                if progress and int(elapsed//2)!=last:
                    last=int(elapsed//2)
                    progress({'phase':'case','case_index':case_index,'case_count':case_count,
                              'elapsed_seconds':round(elapsed,2),'message':f'正在执行第 {case_index}/{case_count} 组实例'})
                time.sleep(.1)
        except BaseException:
            _stop(process)
            raise
    return {'status':'completed' if process.returncode==0 else 'runner_error',
            'exit_code':process.returncode,'elapsed_seconds':time.monotonic()-started}


def _copy_submission(source,destination):
    if source.is_dir():shutil.copytree(source,destination);target=destination
    else:
        # Keep sibling helper modules with an explicitly selected file entrypoint.
        shutil.copytree(source.parent,destination);target=destination/source.name
    for p in destination.rglob('*'):
        if not p.is_symlink():p.chmod(0o755 if p.is_dir() or p.stat().st_mode&0o111 else 0o644)
    destination.chmod(0o755)
    return target


def _redact(value,seed):
    if type(value) is str:return value.replace(str(seed),'<sealed>')
    if type(value) is list:return [_redact(v,seed) for v in value]
    if type(value) is dict:return {k:_redact(v,seed) for k,v in value.items() if k not in ('seed','case_seeds','command')}
    return value


def grade_match(private_spec,submission_path,output_dir,*,timeout=300,metrics=None,verified_metrics=False,
                cancel_event=None,progress=None):
    validate_private(private_spec)
    if not _number(timeout) or timeout<=0:raise ValueError('timeout must be positive and finite')
    if type(verified_metrics) is not bool:raise ValueError('verified_metrics must be an explicit host verification boolean')
    source=Path(submission_path).resolve(strict=True)
    destination=Path(output_dir).resolve();destination.mkdir(parents=True,exist_ok=True)
    if source.is_dir() and destination.is_relative_to(source):raise ValueError('output cannot be inside the submitted directory')
    if source.is_file() and destination.is_relative_to(source.parent):raise ValueError('output cannot be inside the entrypoint sibling directory')
    task=private_spec['task_id'];rows=[];cancelled=False
    for i,seed in enumerate(private_spec['case_seeds'],1):
        if cancel_event is not None and cancel_event.is_set():cancelled=True;break
        case_dir=destination/f'case-{i:02d}'
        if case_dir.exists():raise ValueError('case output already exists; use a fresh grading directory')
        case_dir.mkdir()
        candidate=_copy_submission(source,case_dir/'submission')
        report_dir=case_dir/'judge'
        command=[sys.executable,str(ROOT/'scripts'/'extreme.py'),'--task',task,'--scale',private_spec['fixture_scale'],
                 '--seed',str(seed),'--submission',str(candidate),'--output',str(report_dir),'--timeout',str(timeout)]
        execution=_run(command,case_dir,timeout+15,cancel_event,progress,i,len(private_spec['case_seeds']))
        row={'index':i,'status':execution['status'],'valid':None,'legal':None,'completed':None,'raw_score':None,'selected_checks':[],
             'summary':'判定待定','failures':[],'judge_seconds':execution['elapsed_seconds']}
        report_path=report_dir/f'{task}.json'
        if execution['status']=='cancelled':cancelled=True;row['summary']='用户取消，本实例未判'
        elif execution['status']=='completed' and report_path.exists():
            try:
                report=json.loads(report_path.read_text())
                if report.get('task_id')!=task or report.get('seed')!=seed or report.get('scale')!=private_spec['fixture_scale']:
                    raise ValueError('runner returned another instance')
                selected=score_report(report,private_spec)
                row.update(_redact(selected,seed),status='passed' if selected['completed'] else 'partial' if selected['valid'] else 'candidate_failed',
                           report_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest())
            except (ValueError,KeyError,TypeError) as exc:row.update(status='environment_error',summary=str(exc),failures=[str(exc)])
        else:row.update(status='environment_error' if execution['status']!='runner_timeout' else 'runner_timeout',
                        summary='裁判运行未完成，不能认作候选质量零分',failures=[execution['status']])
        (case_dir/'execution-private.json').write_text(json.dumps({'command':command,'execution':execution},indent=2)+'\n')
        rows.append(row)
        if cancelled:break
    unknown=cancelled or len(rows)!=private_spec['cases'] or any(r['valid'] is None for r in rows)
    valid=None if unknown else all(r['valid'] for r in rows)
    completed=None if unknown else all(r['completed'] for r in rows)
    quality=None if unknown else statistics.fmean(r['raw_score'] for r in rows)
    if valid is False and (task.startswith('R') or any(r.get('severe_foundation_failure') for r in rows)):quality=0
    efficiency=score_efficiency(quality,valid,metrics or {},private_spec['budgets'],profile=private_spec['efficiency_profile'],trusted=verified_metrics)
    review=task.startswith('F')
    result={'task_id':task,'tier':private_spec['tier'],'scope':private_spec['scope'],'scope_id':private_spec['scope_id'],
            'commitment':private_spec['commitment'],'fixture_scale':private_spec['fixture_scale'],
            'valid':valid,'legal':valid,'completed':completed,'raw_score':quality,
            'status':'cancelled' if cancelled else 'environment_error' if unknown else 'passed' if completed else 'partial' if valid else 'candidate_failed',
            'cases':rows,'selected_checks':sorted({c['name'] for row in rows for c in row['selected_checks']}),
            'codex_review_required':review,'review_scope':private_spec['review_scope'],
            'score_scope':'semantic_only' if review else 'continuous_objective' if task.startswith('R') else 'machine_contract',
            'complete_frontend_score':None if review else 'not_applicable',
            'efficiency_score':efficiency['adjusted_quality'],'efficiency_eligible':efficiency.get('status')=='scored',
            'efficiency':efficiency,'judge_runtime_used_as_agent_time':False}
    (destination/'match-grade.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    if progress:progress({'phase':'complete','case_count':len(rows),'message':'机器判定完成；前端完整体验仍待独立评审' if review else '机器判定完成'})
    return result
