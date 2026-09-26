"""Local immutable draws and inert answer sealing. Public views never expose host seeds."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path,PurePosixPath
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ID=re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}$')


def now():return datetime.now(timezone.utc).isoformat()
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def identity(value):
    if type(value) is not str or not ID.fullmatch(value):raise ValueError('invalid identifier')
    return value
def read(path):return json.loads(Path(path).read_text())
def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(canonical(value)+b'\n');stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
def exclusive(path,value):
    """Publish a complete JSON document once; readers never observe partial bytes."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);encoded=canonical(value)+b'\n'
    fd,name=tempfile.mkstemp(prefix='.exclusive-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(encoded);stream.flush();os.fsync(stream.fileno())
        os.link(name,path)  # same-directory atomic creation; refuses an existing official record
    finally:
        if os.path.exists(name):os.unlink(name)
def readonly(root):
    for path in sorted(Path(root).rglob('*'),reverse=True):path.chmod(0o555 if path.is_dir() else 0o444)
    Path(root).chmod(0o555)
def writable(root):
    Path(root).chmod(0o755)
    for path in Path(root).rglob('*'):path.chmod(0o755 if path.is_dir() else 0o644)


def inventory(root):
    from integrations.cli import source_files
    return [{'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            for name,data in sorted(source_files(root).items())]


def entrypoint(root,value):
    if type(value) is not str or not value or '\\' in value or '\x00' in value:raise ValueError('entrypoint must be relative')
    relative=PurePosixPath(value)
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('entrypoint escapes sealed payload')
    target=(Path(root)/value).resolve(strict=True)
    if not target.is_relative_to(Path(root).resolve()):raise ValueError('entrypoint escapes sealed payload')
    return target


def fingerprints(task):
    track={'R':'reasoning','C':'code','F':'frontend'}[task[0]]
    files=[ROOT/'arena'/'rules.py',ROOT/'arena'/'judge.py',ROOT/'arena'/'server.py',ROOT/'arena'/'storage.py',ROOT/'scripts'/'extreme.py',
           ROOT/'scripts'/'launch_arena.py',
           ROOT/'organizer'/'extreme_contract.py',ROOT/'organizer'/'efficiency.py']
    files+=list((ROOT/track).glob('extreme*.py'))
    files+=list((ROOT/track/task).rglob('*.py'))
    return {str(path.relative_to(ROOT)):digest(path) for path in files if path.is_file()}


def export_task(task,scale,destination):
    track={'R':'reasoning','C':'code','F':'frontend'}[task[0]]
    command=[sys.executable,'-B',str(ROOT/track/'extreme.py'),'--task',task,'--scale',scale,
             '--seed','260926','--export',str(destination)]
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=180)
    if result.returncode:raise RuntimeError('public task export failed: '+result.stderr[-1200:])


class ArenaStore:
    def __init__(self,root=None,*,draw_factory=None,exporter=None):
        self.root=Path(root or ROOT/'reports'/'arena').resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.root.chmod(0o700);self.matches=self.root/'matches';self.matches.mkdir(exist_ok=True)
        self.lock=threading.RLock();self.draw_factory=draw_factory;self.exporter=exporter or export_task

    def folder(self,match_id):
        folder=self.matches/identity(match_id)
        if folder.is_symlink() or not folder.is_dir():raise FileNotFoundError('match not found')
        return folder

    def create_draw(self,task,tier,track='all'):
        from arena.rules import TASKS
        if type(track) is not str or track not in ('all','R','C','F'):
            raise ValueError('track must be all, R, C or F')
        eligible=[tid for tid in TASKS if track=='all' or tid.startswith(track)]
        random_task=task=='random'
        if random_task:task=secrets.choice(eligible)
        elif type(task) is not str or task not in eligible:
            raise ValueError('task does not belong to the requested pool')
        selection={'mode':'random' if random_task else 'fixed','track':track,
                   'eligible_tasks':eligible if random_task else [task],'task_id':task}
        if self.draw_factory is None:
            from arena.rules import draw_spec
            factory=draw_spec
        else:factory=self.draw_factory
        draw=factory(task,tier)
        if not {'public','private'}<=set(draw):raise ValueError('draw factory omitted public/private scopes')
        public=draw['public']
        if public['task_id']!=task:raise ValueError('draw factory changed the selected task')
        task=public['task_id'];tier=public['tier'];identity(task);identity(tier)
        match_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+secrets.token_hex(4)
        folder=self.matches/match_id;folder.mkdir(mode=0o700)
        try:
            private=folder/'private';private.mkdir(mode=0o700)
            # Freeze the draw before material generation; no API ever rewrites this file.
            record={'id':match_id,'created_at':now(),'public':public,'private':draw['private'],
                    'source_fingerprints':fingerprints(task),'selection':selection}
            atomic(private/'draw.json',record);(private/'draw.json').chmod(0o444)
            atomic(private/'anchor.json',{'draw_sha256':digest(private/'draw.json')});(private/'anchor.json').chmod(0o444)
            public_dir=folder/'public';self.exporter(task,public.get('fixture_scale','smoke'),public_dir)
            public_dir.mkdir(exist_ok=True)
            match_text='# 本轮比赛 / '+task+'\n\n抽签标识：'+match_id+'\n\n'
            match_text+='选题方式：'+('服务端均匀随机抽题' if random_task else '指定题目')+'；题池：'+', '.join(selection['eligible_tasks'])+'。\n\n'
            match_text+='本轮要求由 MATCH.md 固定，原题完整档仅作接口与背景材料。请按本轮阶段完成实验、自测和答案，再由主办方封存独立评分。\n\n'
            match_text+='```json\n'+json.dumps(public,ensure_ascii=False,indent=2)+'\n```\n\n'
            match_text+='先下载公开ZIP并解压，或将本题包复制到自己的可写工作目录，再修改工作副本中的 submission/、policy.py 或对应入口。不要修改启动器保存的只读原件。不要把观察型 smoke 当作评分通过；不得访问主办方私有数据。提交时提供可写工作副本的目录/ZIP及相对 entrypoint。\n'
            (public_dir/'MATCH.md').write_text(match_text)
            (public_dir/'ARENA_README.md').write_text('# 开始本轮\n\n先读 MATCH.md，再读公开协议和阶段材料。先下载解压或复制到自己的可写目录后修改，不要修改启动器保存的只读原件。只在自己的工作副本中实验和编写答案；本启动器不会自动运行模型。\n\n完成后在本地比赛界面提交工作副本目录或ZIP，封存后再点“自动检验”。时间/token自报仅作待核验资料。\n')
            atomic(private/'public_inventory.json',inventory(public_dir));(private/'public_inventory.json').chmod(0o444)
            with zipfile.ZipFile(folder/'public.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(public_dir.rglob('*')):
                    if path.is_file():archive.write(path,path.relative_to(public_dir).as_posix())
            atomic(private/'archive.json',{'sha256':digest(folder/'public.zip')});(private/'archive.json').chmod(0o444)
            readonly(public_dir)
            atomic(folder/'state.json',{'status':'ready','created_at':record['created_at']})
            return self.public_match(match_id)
        except BaseException as exc:
            atomic(folder/'state.json',{'status':'draw_failed','created_at':now(),'error':str(exc)[:1000]})
            raise

    def verify_draw(self,match_id):
        folder=self.folder(match_id);private=folder/'private';anchor=read(private/'anchor.json')
        if digest(private/'draw.json')!=anchor['draw_sha256']:raise ValueError('draw commitment record was modified')
        record=read(private/'draw.json')
        if record['id']!=match_id:raise ValueError('draw belongs to another match')
        if record['source_fingerprints']!=fingerprints(record['public']['task_id']):raise ValueError('host evaluator changed since this draw; create a new match')
        if inventory(folder/'public')!=read(private/'public_inventory.json'):raise ValueError('public task bundle was modified')
        if digest(folder/'public.zip')!=read(private/'archive.json')['sha256']:raise ValueError('public archive was modified')
        return record

    def submit(self,match_id,participant,source,entry=None,metrics_path=None):
        from integrations.cli import source_files
        from scripts.experiment import metrics_record
        if type(participant) is not str or not participant.strip() or len(participant)>100:raise ValueError('participant must be 1..100 characters')
        participant=participant.strip();folder=self.folder(match_id)
        with self.lock:
            self.verify_draw(match_id)
            for path in (folder/'submissions').glob('*/sealed/manifest.json'):
                if read(path)['participant']==participant:raise ValueError('participant already has a sealed answer; create another match for a new attempt')
            source=Path(source).absolute()
            if source.is_dir() and self.root.is_relative_to(source.resolve()):raise ValueError('source contains arena private storage')
            files=source_files(source)
            if entry is None:
                if source.is_file() and not zipfile.is_zipfile(source):entry=source.name
                else:raise ValueError('directory/ZIP submission needs an explicit relative entrypoint')
            sid='s-'+secrets.token_hex(8);submission=folder/'submissions'/sid;submission.mkdir(parents=True)
            temporary=Path(tempfile.mkdtemp(prefix='.import-',dir=submission));payload=temporary/'payload';payload.mkdir()
            try:
                for name,data in files.items():
                    target=payload/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
                entrypoint(payload,entry)
                metrics=metrics_record(metrics_path)
                for evidence in metrics.get('evidence_files',[]):entrypoint(payload,evidence)
                atomic(temporary/'metrics.json',metrics)
                manifest={'id':sid,'match_id':match_id,'participant':participant,'entrypoint':entry,
                          'submitted_at':now(),'files':inventory(payload),'metrics_sha256':digest(temporary/'metrics.json')}
                atomic(temporary/'manifest.json',manifest)
                anchor={'manifest_sha256':digest(temporary/'manifest.json'),'sealed_at':now()}
                atomic(folder/'private'/('receipt-'+sid+'.json'),anchor)
                os.rename(temporary,submission/'sealed');temporary=None;readonly(submission/'sealed')
                return self.submission_view(match_id,sid)
            finally:
                if temporary is not None:shutil.rmtree(temporary,ignore_errors=True)

    def verify_submission(self,match_id,sid):
        self.verify_draw(match_id);folder=self.folder(match_id);sealed=folder/'submissions'/identity(sid)/'sealed'
        if sealed.is_symlink():raise ValueError('sealed answer must not be a symlink')
        anchor=read(folder/'private'/('receipt-'+sid+'.json'))
        if digest(sealed/'manifest.json')!=anchor['manifest_sha256']:raise ValueError('sealed manifest was modified')
        manifest=read(sealed/'manifest.json')
        if manifest['files']!=inventory(sealed/'payload'):raise ValueError('sealed answer files were modified')
        if manifest['metrics_sha256']!=digest(sealed/'metrics.json'):raise ValueError('sealed metrics were modified')
        entrypoint(sealed/'payload',manifest['entrypoint'])
        return sealed,manifest

    def submission_view(self,match_id,sid):
        folder=self.folder(match_id);sealed=folder/'submissions'/identity(sid)/'sealed';manifest=read(sealed/'manifest.json')
        view={k:manifest[k] for k in ('id','participant','entrypoint','submitted_at')}
        view.update(status='sealed',seal_sha256=digest(sealed/'manifest.json'),raw_score=None,relative_score=None,
                    metrics_trust='unverified',efficiency_eligible=False)
        official=folder/'private'/('official-'+sid+'.json')
        grade=official if official.exists() else folder/'private'/('latest-'+sid+'.json')
        if grade.exists():view.update(self.public_grade(match_id,read(grade)))
        verified=folder/'private'/('review-'+sid+'.json')
        if verified.exists():
            proof=read(verified);binding=self.review_binding(match_id,sid)
            if proof['binding']==binding:
                result=proof['efficiency']
                view.update(metrics_trust='independently_verified',efficiency_eligible=result.get('status')=='scored',
                            efficiency_score=result.get('adjusted_quality'),efficiency_status=result.get('status'),
                            efficiency_profile_id=result.get('score_profile_id'),reviewed_at=proof['imported_at'])
            else:view.update(metrics_trust='verification_binding_changed',efficiency_eligible=False,efficiency_score=None)
        return view

    def public_match(self,match_id):
        folder=self.folder(match_id);record=read(folder/'private'/'draw.json');public=record['public']
        state=read(folder/'state.json')
        submissions=[self.submission_view(match_id,path.name) for path in sorted((folder/'submissions').glob('*')) if (path/'sealed'/'manifest.json').is_file()]
        return {'id':match_id,'task_id':public['task_id'],'tier':public['tier'],'created_at':record['created_at'],
                'status':state['status'],'commitment':public['commitment'],'public_scope':public,
                'selection':record.get('selection',{'mode':'fixed','task_id':public['task_id']}),
                'stages':public.get('prompt_segments',[]),'submissions':submissions,
                'public_bundle_path':str(folder/'public'),'download_url':'/api/matches/'+match_id+'/download'}

    def list_matches(self):
        result=[]
        for folder in sorted(self.matches.iterdir(),reverse=True):
            if folder.is_dir() and (folder/'private'/'draw.json').is_file():
                try:result.append(self.public_match(folder.name))
                except (OSError,ValueError,KeyError):continue
        return result

    def _redact(self,match_id,value):
        record=read(self.folder(match_id)/'private'/'draw.json')
        seeds=[]
        def collect(v):
            if isinstance(v,dict):
                for key,item in v.items():
                    if 'seed' in key and 'commit' not in key:collect_seed(item)
                    else:collect(item)
            elif isinstance(v,list):
                for item in v:collect(item)
        def collect_seed(v):
            if isinstance(v,(int,str)):seeds.append(str(v))
            elif isinstance(v,dict):
                for item in v.values():collect_seed(item)
            elif isinstance(v,list):
                for item in v:collect_seed(item)
        collect(record['private'])
        forbidden={'seed','case_seed','case_seeds','private','private_spec','command','execution','judge_report','submission_path'}
        def scrub(v):
            if isinstance(v,dict):return {key:scrub(item) for key,item in v.items() if key not in forbidden and not ('seed' in key and 'commit' not in key)}
            if isinstance(v,list):return [scrub(item) for item in v]
            if isinstance(v,str):
                for seed in seeds:
                    if len(seed)>=4:v=v.replace(seed,'[private seed]')
                return v
            return v
        return scrub(value)

    def public_grade(self,match_id,grade):
        raw=grade.get('raw_score');valid=grade.get('legal',grade.get('valid'))
        valid=valid if type(valid) is bool else None
        completed=grade.get('completed',valid);completed=completed if type(completed) is bool else None
        if raw is not None and (type(raw) not in (int,float) or not math.isfinite(raw)):raw=None
        pending=bool(grade.get('codex_review_required'))
        status=('failed' if valid is None else 'invalid' if valid is False else
                'review_pending' if pending else 'graded' if completed else 'partial')
        cases=grade.get('cases',[]);cases=cases if isinstance(cases,list) else []
        safe_cases=[]
        for index,case in enumerate(cases):
            if not isinstance(case,dict):continue
            safe={key:case[key] for key in ('index','status','valid','legal','completed','raw_score','summary','failures','selected_checks') if key in case}
            safe.setdefault('index',index+1);safe_cases.append(safe)
        view={'valid':valid,'legal':valid,'completed':completed,'raw_score':raw,'status':status,'codex_review_required':pending,
              'review_scope':grade.get('review_scope'),'scope':grade.get('scope'),
              'score_scope':grade.get('score_scope'),'selected_checks':grade.get('selected_checks',[]),
              'official':grade.get('official',False),'grade_id':grade.get('grade_id'),
              'cases_count':len(cases),'passed_cases':sum(c.get('completed',c.get('valid')) is True for c in cases if isinstance(c,dict)),
              'cases':safe_cases,'metrics_trust':'unverified','efficiency_eligible':False,
              'graded_at':grade.get('graded_at')}
        if grade.get('error'):view['error']=str(grade['error'])[:1500]
        return self._redact(match_id,view)

    def reports(self,match_id):
        match=self.public_match(match_id);reports=[]
        for submission in match['submissions']:
            if submission['status']!='sealed':reports.append(dict(submission,submission_id=submission['id']))
        return {'match_id':match_id,'reports':reports}

    def leaderboard(self,match_id):
        entries=self.public_match(match_id)['submissions']
        eligible=[e for e in entries if e.get('valid') is True and type(e.get('raw_score')) in (int,float)]
        best=max((e['raw_score'] for e in eligible),default=0)
        eligible_ids={e['id'] for e in eligible}
        for entry in entries:
            entry['relative_score']=(round(100*entry['raw_score']/best,6) if entry['id'] in eligible_ids and best>0 else
                                     0 if type(entry.get('raw_score')) in (int,float) else None)
        efficient=[e for e in eligible if e.get('efficiency_eligible') and type(e.get('efficiency_score')) in (int,float)]
        best_efficiency=max((e['efficiency_score'] for e in efficient),default=0)
        for entry in entries:
            entry['efficiency_relative_score']=(round(100*entry['efficiency_score']/best_efficiency,6)
                if entry.get('efficiency_eligible') and best_efficiency>0 else 0 if entry.get('efficiency_eligible') else None)
        entries.sort(key=lambda e:(e.get('relative_score') is None,-(e.get('relative_score') or 0),e['submitted_at']))
        winners=[e['id'] for e in eligible if best>0 and e['raw_score']==best]
        semantic=self.public_match(match_id)['task_id'].startswith('F')
        return {'match_id':match_id,'entries':entries,'champion':winners[0] if winners else None,'champions':winners,
                'champion_scope':'semantic_only' if semantic else 'machine_quality',
                'complete_frontend_champion':None if semantic else 'not_applicable',
                'efficiency_champion':next((e['id'] for e in efficient if e['efficiency_score']==best_efficiency),None)
                    if best_efficiency>0 and len(efficient)==len(eligible) else None,
                'efficiency_ranking_complete':bool(eligible) and len(efficient)==len(eligible),
                'all_invalid':bool(entries) and all(e.get('valid') is False for e in entries),
                'comparison_scope':'same immutable draw; frontend rank is semantic only; efficiency unverified'}

    def review_binding(self,match_id,sid):
        record=self.verify_draw(match_id);sealed,manifest=self.verify_submission(match_id,sid)
        official=self.folder(match_id)/'private'/('official-'+identity(sid)+'.json')
        if not official.is_file():raise ValueError('independent review requires a frozen official machine grade')
        policy={'profile':record['private'].get('efficiency_profile','elapsed_only'),'budgets':record['private']['budgets']}
        return {'match_id':match_id,'submission_id':sid,'commitment':record['public']['commitment'],
                'seal_sha256':digest(sealed/'manifest.json'),'quality_sha256':digest(official),
                'efficiency_policy_sha256':hashlib.sha256(canonical(policy)).hexdigest()}

    def import_review(self,review_path):
        """Trusted organizer CLI only. Never called from the participant HTTP API."""
        from integrations.cli import ensure_plain_parents
        from organizer.efficiency import score_efficiency
        path=Path(review_path);ensure_plain_parents(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size>1024*1024:raise ValueError('review must be a regular JSON file <=1 MiB')
        value=read(path)
        if value.get('artifact_type')!='codex-arena-review':raise ValueError('independent Codex review artifact required')
        binding=value.get('binding',{});mid=identity(binding.get('match_id'));sid=identity(binding.get('submission_id'))
        with self.lock:
            expected=self.review_binding(mid,sid)
            if binding!=expected:raise ValueError('review does not bind the frozen draw, seal, quality and efficiency policy')
            if value.get('reviewer')!='Codex' or value.get('independent_evidence_verified') is not True:
                raise ValueError('organizer must supply a completed independent Codex evidence review')
            evidence=value.get('evidence_files')
            if not isinstance(evidence,list) or not 1<=len(evidence)<=20:raise ValueError('1..20 independent host/provider evidence files required')
            checked=[]
            for item in evidence:
                if not isinstance(item,dict) or item.get('kind') not in ('host_log','provider_usage'):raise ValueError('evidence kind must be host_log or provider_usage')
                source=Path(item['path']);ensure_plain_parents(source)
                if source.is_symlink() or not source.is_file() or source.stat().st_size>64*1024*1024:raise ValueError('invalid evidence file')
                if source.resolve().is_relative_to(self.folder(mid)/'submissions'):raise ValueError('participant-sealed files alone are not independent host evidence')
                if digest(source)!=item.get('sha256'):raise ValueError('evidence SHA does not match the reviewed file')
                checked.append({'kind':item['kind'],'sha256':item['sha256'],'path':str(source.resolve())})
            metrics=value.get('verified_metrics')
            if not isinstance(metrics,dict):raise ValueError('verified_metrics must be an object')
            allowed={'total_ms','ttft_ms','output_tokens','reasoning_tokens','logical_total_ms','logical_ttft_ms',
                     'logical_output_tokens','logical_reasoning_tokens','simulated','logical_final'}
            if set(metrics)-allowed:raise ValueError('verified metrics contains unsupported fields')
            record=self.verify_draw(mid);official=read(self.folder(mid)/'private'/('official-'+sid+'.json'))
            efficiency=score_efficiency(official.get('raw_score'),official.get('valid'),metrics,record['private']['budgets'],
                                        profile=record['private'].get('efficiency_profile','elapsed_only'),trusted=True)
            if efficiency['status']!='scored':raise ValueError('review cannot produce a verified efficiency score: '+efficiency['status'])
            destination=self.folder(mid)/'private'/('review-'+sid+'.json')
            artifact={'binding':binding,'reviewer':'Codex','imported_at':now(),'evidence_files':checked,
                      'review_sha256':digest(path),'verified_metrics':metrics,'efficiency':efficiency,
                      'authorization':'explicit trusted organizer CLI import; participant source labels were not trusted'}
            exclusive(destination,artifact);destination.chmod(0o444)
            return {'match_id':mid,'submission_id':sid,'efficiency_eligible':True,
                    'efficiency_score':efficiency['adjusted_quality'],'policy_id':efficiency['score_profile_id']}

    def grading_request(self,match_id):
        match=self.public_match(match_id)
        bindings=[]
        for submission in match['submissions']:
            try:bindings.append(self.review_binding(match_id,submission['id']))
            except (ValueError,OSError):pass
        binding_text=json.dumps(bindings,ensure_ascii=False,indent=2)
        return f'''# 独立 Codex 评分任务

比赛：{match_id}；题目：{match['task_id']}；档位：{match['tier']}。
抽签承诺：{match['commitment']}。
本机记录目录：{self.folder(match_id)}。

先读取公开 MATCH.md、已封存答案manifest与独立自动检验结果。核对draw、public inventory、源码版本与sealed SHA；不能修改封存答案或把参赛者自报成功当作通过。按本轮public_scope逐项复核实际功能、测试证据和阶段要求。前端视觉、键盘、交互与可访问性须实际检查，未检查就保留pending。

时间/token目前标为unverified。只有核对独立host/API证据后才可进入效率分；不得用自动裁判运行时间冒充模型思考时间。报告原始质量分、相对分、证据、失败、未核验项，并说明这是独立评分而非答案作者自评。所有私有seed只能在host内部使用，不抄入公开报告。

## 核验完成后的效率分导入

仅由可信主办方在独立核验后执行，参赛者HTTP提交不能宣称trusted：

    python3 scripts/launch_arena.py --import-review /absolute/path/review.json

review.json必须含artifact_type="codex-arena-review"、reviewer="Codex"、independent_evidence_verified=true、verified_metrics（实际host/API时间与token；不得填裁判运行时间）和evidence_files数组（每项kind为host_log/provider_usage、path为独立证据文件、sha256为复核摘要）。binding必须逐字段使用下方对应选手的冻结绑定；没有官方机器结果时不能导入。首份受信复核冻结，不能挑选反复调整后的最优分。

```json
{binding_text}
```

前端完整体验仍需实际独立检查；仅完成指标复核不会把视觉待评改成通过。这是供用户交给Codex的评分任务说明；下载它不会调用模型，也不表示Codex已经完成评分。
'''
