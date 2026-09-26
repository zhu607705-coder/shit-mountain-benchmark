"""Frozen, scope-aware local contest tiers. Tier names are not calibrated win rates."""
from __future__ import annotations
import copy
import hashlib
import json
import secrets

VERSION='arena-scope-2'
TASKS={
 'R1':('多阶段投资与资源调度','reasoning','diamond','不可逆投资、跨链质量与在线信息需联合规划'),
 'R2':('检查会改变系统的主动诊断','reasoning','diamond','实验副作用、机制漂移和条件策略耦合'),
 'R3':('互补探针与双故障预算','reasoning','king','单步无信息探针需要组合选择与相关后验'),
 'R4':('库存、维护与在线排程','reasoning','king','低价值前驱、磨损和耗材重启损失相互作用'),
 'C1':('多租户账本与跨账本补偿','code','diamond','迁移恢复与stage补偿、关闭屏障需共同满足'),
 'C2':('持久化构建与执行时缓存','code','king','动态依赖、版本冲突与发布恢复耦合'),
 'C3':('耐久事务与崩溃恢复','code','nightmare','事务、范围冲突、崩溃窗口与回收边界需一致'),
 'C4':('非密闭DAG与工件发布','code','nightmare','负依赖、深图和中断发布组合失效'),
 'F1':('事故台身份与确认协作','frontend','gold','身份别名、导航与并发确认要求一致'),
 'F2':('离线实验排程与冲突','frontend','diamond','并发字段合并后仍须检查跨记录约束'),
 'F3':('流式快照、暂停与墓碑','frontend','king','历史视图、大量导出和安全回收互相约束'),
 'F4':('多窗口因果编辑与撤销','frontend','king','因果撤销、导入原子性和代际恢复耦合')}
TIERS=[
 {'id':'bronze','name':'青铜','rank':1,'fixture_scale':'smoke','cases':1,'total_ms':300000,'output_tokens':8192,'scope_label':'一个明确公开的控制检查；R仅首个事故'},
 {'id':'silver','name':'白银','rank':2,'fixture_scale':'smoke','cases':1,'total_ms':600000,'output_tokens':12288,'scope_label':'指定机制家族；R至多四个事故'},
 {'id':'gold','name':'黄金','rank':3,'fixture_scale':'smoke','cases':2,'total_ms':1200000,'output_tokens':24576,'scope_label':'完整smoke合约，代码含stage-v2'},
 {'id':'diamond','name':'钻石','rank':4,'fixture_scale':'full','cases':1,'total_ms':1800000,'output_tokens':32768,'scope_label':'完整full合约'},
 {'id':'king','name':'王者','rank':5,'fixture_scale':'full','cases':3,'total_ms':1800000,'output_tokens':49152,'scope_label':'三组独立full实例，全部必须通过'},
 {'id':'nightmare','name':'噩梦','rank':6,'fixture_scale':'full','cases':5,'total_ms':1200000,'output_tokens':49152,'scope_label':'五组独立full实例，更紧总作答时间'}]
CODE_BRONZE={
 'C1':['concurrent_legacy_migration'],
 'C2':['snapshot_alias_cancel_worker_loss_retry_restart'],
 'C3':['immutable_snapshot_compaction_idempotency_concurrent_readers'],
 'C4':['cross_root_epoch_change_delete_repair_order_history']}
CODE_SILVER={
 'C1':['concurrent_legacy_migration','migration_lost_ack_lease_steal_late_conflict','epoch_replay_isolation_projection_restart'],
 'C2':['snapshot_alias_cancel_worker_loss_retry_restart','deep_shared_dag_scale_boundary'],
 'C3':['immutable_snapshot_compaction_idempotency_concurrent_readers'],
 'C4':['cross_root_epoch_change_delete_repair_order_history','concurrent_publish_then_new_epoch']}
FRONT_BRONZE={'F1':['full initial population is available'],'F2':['all initial tasks are present'],
              'F3':['full initial population is available'],'F4':['all initial tasks are present']}
FRONT_SILVER={
 'F1':['full initial population is available','undoing one acknowledgement preserves an unseen concurrent acknowledgement','alias chain rewrites selection focus and acknowledgement identity'],
 'F2':['all initial tasks are present','failed persistence leaves current intent visible and does not claim saved','refresh after successful persistence recovers both offline edits'],
 'F3':['full initial population is available','a paused view stays on one coherent historical snapshot','an unpaused second view observes newest versions'],
 'F4':['all initial tasks are present','sequential remote editing is not classified as concurrent conflict','identical event replay is idempotent']}


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def normalize_tier(tier):
    for value in TIERS:
        if tier in (value['id'],value['name']):return value['id']
    raise ValueError('unknown tier')


def catalog():
    return {'version':VERSION,'calibration':'scope specification; empirical model win rates have not been calibrated',
            'tasks':[{'id':task,'title':v[0],'track':v[1],'recommended_tier':v[2],'tier_reason':v[3]} for task,v in TASKS.items()],
            'tiers':copy.deepcopy(TIERS)}


def scope_for(task,tier):
    tier=normalize_tier(tier)
    if task not in TASKS:raise ValueError('unknown task')
    broad=tier not in ('bronze','silver')
    if task.startswith('R'):
        limit=None if broad else 1 if tier=='bronze' else 4
        return {'kind':'reasoning_episodes','episode_limit':limit,'selector':{'mode':'episode_prefix','limit':limit},
                'require_stage_v2':False,'description':('完整生成器的全部事故' if broad else f'每个种子仅前{limit}个事故；不足则全部'),
                'qualification':'selected episodes must all return legal actions; no invented quality threshold',
                'quality':'continuous loss objective, recomputed only on selected episodes'}
    if broad:
        return {'kind':'all_checks','episode_limit':None,'selector':{'mode':'all'},
                'require_stage_v2':task.startswith('C'),'description':'全部机器合约检查'+('，包括必需stage-v2能力和组合用例' if task.startswith('C') else '；只涵盖语义适配器'),
                'qualification':'all selected checks and full protocol must pass',
                'quality':'selected check pass fraction; published foundation failure or missing required stage capability gives zero',
                'foundation_checks':(CODE_BRONZE if task.startswith('C') else FRONT_BRONZE)[task][:]}
    names=(CODE_BRONZE if tier=='bronze' else CODE_SILVER)[task] if task.startswith('C') else (FRONT_BRONZE if tier=='bronze' else FRONT_SILVER)[task]
    patterns=[r'^fault_\d+_commit_write_(before_eio|after_eio|short_enospc|kill_after)$'] if task=='C3' and tier=='silver' else []
    return {'kind':'selected_checks','episode_limit':None,'selector':{'mode':'named','names':names[:],'patterns':patterns,'minimum_pattern_matches':4 if patterns else 0},
            'require_stage_v2':False,'description':'仅以下公开检查参与判定：'+'；'.join(names)+('；commit_write四种故障恢复' if patterns else ''),
            'qualification':'all selected checks pass; unrelated diagnostics and stage-v2 gaps do not count',
            'quality':'selected check pass fraction; published foundation failure or missing required stage capability gives zero',
                'foundation_checks':(CODE_BRONZE if task.startswith('C') else FRONT_BRONZE)[task][:]}


def _public(task,tier):
    if task not in TASKS:raise ValueError('unknown task')
    tier=normalize_tier(tier);definition=next(x for x in TIERS if x['id']==tier);scope=scope_for(task,tier)
    budgets={'total_ms':definition['total_ms'],'ttft_ms':min(60000,definition['total_ms']//10),
             'output_tokens':definition['output_tokens'],'reasoning_tokens':definition['output_tokens'],
             'max_penalty':.3,'time_weight':.6}
    identity={'version':VERSION,'task_id':task,'tier':tier,'scope':scope,'fixture_scale':definition['fixture_scale'],
              'cases':definition['cases'],'budgets':budgets,'efficiency_profile':'elapsed_only'}
    result={**identity,'title':TASKS[task][0],'track':TASKS[task][1],'tier_name':definition['name']}
    sections=[
      ('locate','复现与定位',.2,['公共PROMPT/协议','当前档位公开检查名单或事故数量'],
       ['最小复现或小规模策略对照','接口入口、失败证据与边界说明'],
       '先阅读公开材料，只围绕本档范围建立最小复现或策略对照。定位影响这些可观察结果的机制；不要把不在范围内的能力当成完成要求。'),
      ('implement','目标机制实现',.55,['第一段定位结果','与所选检查直接相关的工作副本/策略状态'],
       ['可运行提交入口','修复或优化后的实际文件','修改理由及保留的不确定项'],
       '实现满足指定范围的修复或决策策略。联动检查所涉及的依赖、状态和资源；把时间集中到能改变本档裁判结果的机制。'),
      ('verify','范围内完整验证',.25,['第二段可执行答案','本档检查范围与实例数量','已有运行日志'],
       ['可重跑的自测命令和结果','最终入口路径与文件','仍未通过的范围内检查及观测指标'],
       '复跑本档全部所选检查并检查组合副作用。封存真实答案和证据，交给独立裁判；自报成功不能替代判分。')]
    result['prompt_segments']=[{'id':sid,'name':name,'prompt':prompt+'\n当前范围：'+scope['description']+f'；{definition["fixture_scale"]}，{definition["cases"]}组私有实例。',
       'scope':({'locate':'最小可观察复现：'+(str(scope['selector'].get('names',[scope['description']])[0]) if scope['selector'].get('names') else '第一组可见输入与合法动作边界'),
                 'implement':'影响所选结果的实现机制：'+scope['description'],
                 'verify':'全部所选范围及全部'+str(definition['cases'])+'组实例的验证与提交'}[sid]),'materials':materials,'deliverables':outputs,
       'budget':{'total_ms':round(definition['total_ms']*share),'output_tokens':round(definition['output_tokens']*share)}}
       for sid,name,share,materials,outputs,prompt in sections]
    result['review_scope']='semantic checks only; UI/browser/usability remain pending' if task.startswith('F') else 'independent Codex evidence review'
    result['scope_id']=digest(result)
    return result


def draw_spec(task_id,tier,seed=None):
    public=_public(task_id,tier)
    if seed is not None and type(seed) is not int:raise ValueError('seed must be integer or omitted')
    master=secrets.randbits(256) if seed is None else seed
    seeds=[int(digest({'draw':master,'scope_id':public['scope_id'],'case':i})[:15],16) for i in range(public['cases'])]
    commitment=digest({'scope_id':public['scope_id'],'case_seeds':seeds})
    public['commitment']=commitment
    private={**copy.deepcopy(public),'case_seeds':seeds,'seed_commitment':commitment,'public_spec':copy.deepcopy(public)}
    return {'public':public,'private':private}


def validate_private(spec):
    expected=_public(spec['task_id'],spec['tier'])
    for field,value in expected.items():
        if spec.get(field)!=value:raise ValueError('draw contract was modified: '+field)
    seeds=spec.get('case_seeds')
    if type(seeds) is not list or len(seeds)!=expected['cases'] or any(type(s) is not int for s in seeds):
        raise ValueError('invalid private case seeds')
    commitment=digest({'scope_id':spec['scope_id'],'case_seeds':seeds})
    if spec.get('seed_commitment')!=commitment or spec.get('commitment')!=commitment:
        raise ValueError('seed commitment mismatch')
    expected_public={**expected,'commitment':commitment}
    if spec.get('public_spec')!=expected_public:raise ValueError('public spec differs from frozen draw contract')
    return expected_public
