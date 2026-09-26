#!/usr/bin/env python3
"""Aggregate every preregistered attempt, using first completed grading only."""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[1]
_spec=importlib.util.spec_from_file_location('_experiment_for_aggregation',ROOT/'scripts'/'experiment.py')
experiment=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(experiment)
FIELDS=('total_ms','ttft_ms','output_tokens','reasoning_tokens','thinking_time_ms')
LOGICAL={'total_ms':'logical_total_ms','ttft_ms':'logical_ttft_ms',
         'output_tokens':'logical_output_tokens','reasoning_tokens':'logical_reasoning_tokens',
         'thinking_time_ms':'logical_thinking_time_ms'}


def numeric(value):
    return type(value) in (int,float) and math.isfinite(value) and value>=0


def percentile(values,fraction):
    if not values:return None
    ordered=sorted(values);position=(len(values)-1)*fraction
    lower=math.floor(position);upper=math.ceil(position)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(position-lower)


def metric_summary(rows):
    result={'trust':'unverified','used_for_scoring':False,
            'scope':'descriptive sealed claims; source labels do not prove host/API provenance',
            'attempts':len(rows),'simulated_attempts':sum(r.get('metrics',{}).get('simulated') is True for r in rows)}
    for field in FIELDS:
        values=[r.get('observed_metrics',{}).get(field) for r in rows]
        clean=[v for v in values if numeric(v)]
        result[field]={'observations':len(clean),'missing':len(values)-len(clean),
                       'mean':statistics.fmean(clean) if clean else None,
                       'max':max(clean) if clean else None,'p50':percentile(clean,.5),
                       'p95':percentile(clean,.95)}
    return result


def completed_grades(private,item,manifest_sha,record):
    """Check artifacts before ordering; runner_error is not a completed grade."""
    good=[];excluded=[]
    base=private/'results'/item['attempt_id']
    for path in sorted(base.glob('*/grade.json')):
        try:
            grade=experiment.load(path)
            if grade.get('status')=='runner_error':
                excluded.append({'path':str(path),'reason':'runner_error; pending, not a quality failure'})
                continue
            if grade.get('manifest_sha256')!=manifest_sha:
                excluded.append({'path':str(path),'reason':'different sealed manifest'})
                continue
            if grade.get('attempt_id')!=item['attempt_id'] or grade.get('task')!=item['task']:
                raise ValueError('grade identity mismatch')
            candidate=grade.get('candidate_result')
            if grade.get('audit_passed') is not True or type(candidate) is not dict or type(candidate.get('valid')) is not bool:
                raise ValueError('judge audit/validity incomplete')
            timestamp=datetime.fromisoformat(grade['graded_at'])
            if timestamp.tzinfo is None:raise ValueError('grading timestamp must have timezone')
            quality_path=path.parent/'quality.json'
            if Path(grade['quality_artifact']).resolve()!=quality_path.resolve():raise ValueError('quality artifact belongs to another run')
            judge_path=Path(grade['judge_report']).resolve()
            if not judge_path.is_relative_to(path.parent.resolve()):raise ValueError('judge artifact outside grading run')
            judge_hash=experiment.sha(judge_path)
            if judge_hash!=grade['judge_sha256']:raise ValueError('judge artifact fingerprint mismatch')
            judge=experiment.load(judge_path)
            if (judge.get('task_id')!=item['task'] or judge.get('seed')!=record['seeds'][item['task']][str(item['round'])]
                    or judge.get('candidate_result')!=candidate or judge.get('audit_passed') is not True):
                raise ValueError('judge identity, seed or candidate differs')
            quality=experiment.load(quality_path)
            if quality.get('judge_report_sha256')!=judge_hash or quality.get('valid') is not candidate['valid']:
                raise ValueError('quality evidence does not match judge')
            score=quality.get('raw_score')
            if candidate['valid'] is False:
                if score!=0:raise ValueError('invalid candidate quality must be zero')
            elif not numeric(score):raise ValueError('quality score is pending or invalid')
            expected=candidate.get('semantic_score') if item['task'].startswith('F') else candidate.get('raw_score')
            if candidate['valid'] and score!=expected:raise ValueError('quality differs from actual candidate score')
            good.append((timestamp,str(path),grade,quality,quality_path))
        except (OSError,ValueError,KeyError,TypeError) as exc:
            excluded.append({'path':str(path),'reason':str(exc)})
    good.sort(key=lambda item:(item[0],item[1]))
    return good,excluded


def efficiency(selected,metrics,expected_policy_id=None):
    _,path,grade,quality,quality_path=selected
    report_path=Path(path).parent/'efficiency.json'
    result={'score':None,'score_profile_id':None,'status':'efficiency_artifact_missing'}
    if not report_path.exists():return result
    try:
        report=experiment.load(report_path)
        if metrics.get('simulated') is True:raise ValueError('sealed metrics are simulated')
        if report.get('quality_artifact_sha256')!=experiment.sha(quality_path):raise ValueError('quality artifact hash mismatch')
        if report.get('status')!='scored' or report.get('trusted_measurements') is not True:
            raise ValueError('independent host/provider efficiency evidence not scored/verified')
        if report.get('quality_score')!=quality['raw_score'] or report.get('valid') is not quality['valid']:
            raise ValueError('efficiency quality/validity differs from selected grade')
        score=report.get('adjusted_quality')
        if not numeric(score) or score>quality['raw_score']:raise ValueError('invalid adjusted quality')
        profile_id=report.get('score_profile_id')
        policy=report.get('policy')
        if type(policy) is not dict or type(profile_id) is not str:raise ValueError('missing efficiency policy identity')
        computed=hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest()
        if profile_id!=computed:raise ValueError('score profile ID does not match policy/budgets')
        if expected_policy_id is not None and profile_id!=expected_policy_id:raise ValueError('efficiency policy differs from preregistered experiment')
        result.update(score=score,score_profile_id=profile_id,status='verified_artifact',artifact=str(report_path),
                      artifact_sha256=experiment.sha(report_path),policy=policy)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        result['status']='efficiency_pending';result['reason']=str(exc)
    return result


def median_complete(values):
    return statistics.median(values) if values and all(v is not None for v in values) else None


def aggregate(workspace,model='unspecified'):
    workspace,private,record=experiment.context(workspace)
    state=experiment.inspect(workspace)
    experiment.require_controls(state)
    inspected={r['attempt_id']:r for r in state['attempts']}
    plan=record['plan'];assignments=record['assignments']
    expected={(task,variant['id'],round_id) for task in plan['tasks'] for variant in plan['prompt_variants']
              for round_id in range(1,plan['rounds']+1)}
    actual=[(a['task'],a['variant'],a['round']) for a in assignments]
    if len(actual)!=len(expected) or set(actual)!=expected or len({a['attempt_id'] for a in assignments})!=len(actual):
        raise ValueError('organizer assignments do not exactly enumerate the preregistered task/variant/round grid')
    rows=[]
    for item in assignments:
        check=inspected[item['attempt_id']]
        row={k:item[k] for k in ('attempt_id','task','variant','round')}
        row.update(status=check['status'],quality_score=check['quality_score'],raw_quality=None,
                   efficiency_score=None,metrics={},observed_metrics={},selected_grade=None,
                   score_scope='semantic_only' if item['task'].startswith('F') else 'automatic_task_quality')
        if check['status']=='sealed' and not state['task_input_integrity'][item['task']]:
            row.update(status='tampered',quality_score=0,error='shared task inputs changed')
        elif check['status']=='sealed':
            metrics=experiment.load(workspace/'answers'/item['attempt_id']/'sealed'/'metrics.json')
            observed={key:metrics[LOGICAL[key]] if LOGICAL[key] in metrics else metrics.get(key) for key in FIELDS}
            row.update(metrics=metrics,observed_metrics=observed,metrics_trust='unverified',
                       metric_precedence='explicit logical cumulative fields take precedence, including null')
            grades,excluded=completed_grades(private,item,check['manifest_sha256'],record)
            row['excluded_grades']=excluded
            if grades:
                chosen=grades[0];_,path,grade,quality,_=chosen
                eff=efficiency(chosen,metrics,(record.get('efficiency_policy') or {}).get('score_profile_id'))
                row.update(status='graded' if quality['valid'] else 'invalid',
                           quality_score=quality['raw_score'],raw_quality=grade['candidate_result'],
                           selected_grade=path,selected_grade_sha256=experiment.sha(path),
                           selected_manifest_sha256=check['manifest_sha256'],
                           ignored_later_completed_grades=[g[1] for g in grades[1:]],
                           efficiency=eff,efficiency_score=eff['score'])
            else:row.update(status='pending',quality_score=None)
        if row['status'] in ('missing','tampered','invalid'):
            row['efficiency_score']=0
            row['efficiency']={'score':0,'score_profile_id':None,
                               'status':'unconditional_failure_zero; no telemetry required'}
        rows.append(row)
    variants=[];tasks=[];leaderboard=[]
    for task in plan['tasks']:
        task_rows=[r for r in rows if r['task']==task]
        profiles={r['efficiency']['score_profile_id'] for r in task_rows
                  if r['efficiency_score'] is not None and r.get('efficiency',{}).get('score_profile_id') is not None}
        if len(profiles)>1:raise ValueError(f'{task}: refusing mixed efficiency profiles/budgets: '+', '.join(sorted(profiles)))
        per_variant=[]
        for variant in plan['prompt_variants']:
            group=[r for r in task_rows if r['variant']==variant['id']]
            item={'task':task,'variant':variant['id'],'preregistered_rounds':plan['rounds'],
                  'quality_rounds':[r['quality_score'] for r in group],
                  'efficiency_rounds':[r['efficiency_score'] for r in group],
                  'quality_median':median_complete([r['quality_score'] for r in group]),
                  'efficiency_median':median_complete([r['efficiency_score'] for r in group]),
                  'performance':metric_summary(group)}
            variants.append(item);per_variant.append(item)
        quality_values=[v['quality_median'] for v in per_variant]
        efficiency_values=[v['efficiency_median'] for v in per_variant]
        quality=statistics.fmean(quality_values) if all(v is not None for v in quality_values) else None
        adjusted=statistics.fmean(efficiency_values) if all(v is not None for v in efficiency_values) else None
        counts={s:sum(r['status']==s for r in task_rows) for s in ('missing','tampered','pending','invalid','graded')}
        task_summary={'task':task,'quality_score':quality,'efficiency_score':adjusted,
                      'status':'pending' if quality is None else 'aggregated',
                      'score_profile_id':next(iter(profiles)) if profiles else None,
                      'counts':counts,'preregistered_attempts':len(task_rows),
                      'performance':metric_summary(task_rows),
                      'score_scope':'semantic_only' if task.startswith('F') else 'automatic_task_quality',
                      'complete_frontend_score':None if task.startswith('F') else 'not_applicable',
                      'frontend_visual_review':'pending' if task.startswith('F') else 'not_applicable'}
        tasks.append(task_summary)
        leaderboard.append({'model':model,'task_id':task,'task':task,'task_profile':'extreme',
                            'scale':plan['scale'],'comparison_id':record.get('comparison_id'),'raw_score':quality,
                            'efficiency_score':adjusted,'score_profile_id':task_summary['score_profile_id'],
                            'valid':None if quality is None else True,'aggregation':'median_rounds_then_equal_variant_mean',
                            'score_scope':task_summary['score_scope'],
                            'final_ui_leaderboard_eligible':False if task.startswith('F') else None})
    return {'experiment_id':record['id'],'model':model,'profile':'extreme','scale':plan['scale'],
            'comparison_id':record.get('comparison_id'),'cohort_id':record.get('cohort_id'),
            'selection_rule':'earliest completed grade for current sealed manifest; invalid results are retained as zero',
            'aggregation_rule':'median of all preregistered rounds per variant, then equal-weight macro mean over variants; any pending quality propagates',
            'attempts':rows,'variants':variants,'tasks':tasks,'leaderboard_records':leaderboard,
            'counts':{s:sum(r['status']==s for r in rows) for s in ('missing','tampered','pending','invalid','graded')},
            'performance':metric_summary(rows),'performance_is_unverified_descriptive_only':True,
            'organizer_manifest_sha256':experiment.sha(private/'organizer.json')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=True);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--model',default='unspecified')
    args=parser.parse_args()
    try:result=aggregate(args.workspace,args.model)
    except (OSError,ValueError,KeyError,TypeError) as exc:parser.exit(2,'aggregate: '+str(exc)+'\n')
    experiment.write(args.output,result)
    print(json.dumps({'output':str(args.output.resolve()),'counts':result['counts'],
                      'tasks':[{'task':r['task'],'quality_score':r['quality_score'],'efficiency_score':r['efficiency_score']} for r in result['tasks']]},ensure_ascii=False))


if __name__=='__main__':main()
