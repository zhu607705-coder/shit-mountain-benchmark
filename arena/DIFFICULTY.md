# Arena 六档范围与真实判分

六档是**工作范围、实例规模、独立实例数量和作答预算的明确规格**，不是经过多模型试验校准的胜率标签。目录中的 recommended_tier 表示题目完整机制的建议起点；同一题仍可以选择任何档。不能据“噩梦”名称宣称所有模型必败。

| 档位 | 生成规模 | 私有实例组数 | Agent 总作答声明预算 | 输出 token 声明预算 | 实际范围 |
|---|---|---:|---:|---:|---|
| 青铜 bronze | smoke | 1 | 5 分钟 | 8,192 | R 首个事故；C 一个公开控制检查；F 初始载入 |
| 白银 silver | smoke | 1 | 10 分钟 | 12,288 | R 前四个事故，数量不足取全部；C/F 指定检查家族 |
| 黄金 gold | smoke | 2 | 20 分钟 | 24,576 | 所有 smoke 检查；C 包含 stage-v2 必需接口与组合用例 |
| 钻石 diamond | full | 1 | 30 分钟 | 32,768 | 所有 full 检查 |
| 王者 king | full | 3 | 30 分钟 | 49,152 | 三个独立 full 实例，全部应通过 |
| 噩梦 nightmare | full | 5 | 20 分钟 | 49,152 | 五个独立 full 实例，更紧的总作答预算 |

“实例组”是一次完整题目 runner；R runner 自身可能包含多个事故。钻石虽然实例组数少于黄金，但 full 的真实任务/数据规模明显增加。R1/R4 的 smoke 只有两个事故，白银因此使用两个，黄金则对两组不同私有 seed 的完整 smoke 评估，仍有实际区别。

Agent 预算来自冻结的公共 draw，可供宿主实施限制并做效率统计；裁判自身耗时不算 Agent 思考时间。没有可信观测时不得虚构 token、首字时间或内部思考时长。

## 青铜与白银实际检查

C1 青铜只要求 `concurrent_legacy_migration`；白银再要求 `migration_lost_ack_lease_steal_late_conflict` 和 `epoch_replay_isolation_projection_restart`。

C2 青铜要求 `snapshot_alias_cancel_worker_loss_retry_restart`；白银增加 `deep_shared_dag_scale_boundary`。

C3 青铜要求 `immutable_snapshot_compaction_idempotency_concurrent_readers`；白银增加 commit_write 的 before_eio、after_eio、short_enospc、kill_after 四种故障恢复检查。白银不要求其他压缩/替换/目录同步故障族。

C4 青铜要求 `cross_root_epoch_change_delete_repair_order_history`；白银增加 `concurrent_publish_then_new_epoch`，不要求深图边界或 stage-v2。

F1 青铜只验完整初始载入；白银增加并发确认撤销保留他人确认，以及别名链同步选择/焦点/确认身份。F2 青铜只验初始任务；白银增加持久化失败仍保留当前意图，以及成功保存后的刷新恢复。F3 青铜只验初始载入；白银增加暂停视图的历史快照和未暂停视图的新版本。F4 青铜只验初始任务；白银增加顺序远端修改不误报并发，以及相同事件重放幂等。

机器可读的精确检查名称和正则在 `rules.py` 的 scope.selector，公共 draw 会完整提供。实际 runner 可能为诊断执行额外检查，但**未选中的检查失败不影响当前低档资格或得分**；因此低档不会因为尚未要求的 stage-v2 能力而被扣成零。黄金开始要求完整检查，不能借低档选择器跳过 stage-v2。

## 三段 prompt 的投入范围

每场都有独立的三段材料、交付物和预算：

1. **复现与定位，20%**：只读取公共题面、协议及本档检查名单，建立最小可观察复现或首个策略对照，输出入口与失败证据。
2. **目标机制实现，55%**：基于定位结果修改与所选结果直接相关的工作副本、策略状态与依赖，交付真实可运行答案及保留的不确定项。
3. **范围内完整验证，25%**：针对本档全部所选范围和全部实例组完成回归、组合检查、日志与最终文件封存。

这些阶段是不同的实际工作，不是三次改写“请解题”；阶段范围不改变最终冻结的 grading scope。青铜的目标可以很窄，但仍需经历复现、实现和验证三个交付阶段。私有随机种子不出现在 prompt 中。

## 抽签、完成与分数

`draw_spec(task_id, tier, seed=None)` 一次生成全部私有 case_seeds，并用 scope_id 与 seed 列表生成 SHA-256 承诺。相同 draw 的所有选手使用相同实例；不同选手提交不会重新抽签。主办方指定 seed 可以复现抽签，但公共 spec 只含承诺、不含 seed。scope、全部分段 prompt、材料、交付物、分段预算和固定效率 profile 都纳入 scope_id；scope、提示词、预算、公开 spec 或 seed 被修改后，`validate_private` 会拒绝评分。当前契约版本为 arena-scope-2。

R 类完成条件是**所选事故中动作全部合法有效**，没有虚构的 85 分阈值。质量按实际所选事故重新计算 `0.7×平均损失+0.3×最差10%损失`，使用题目原 loss_scale 映射为连续 raw_score。合法但质量差可以完成，仍得到很低原始分；任何所选事故的非法动作使该场 R 得分为 0。

C/F 完成条件是所选检查全部通过；完整范围还要求 runner 的完整协议与退出状态有效。原始质量为所选检查通过率，便于显示部分进展。公开的青铜控制检查构成该题所有档位的基础约束；基础约束失败、缺少高档必需的 stage-v2 能力，或完整范围出现无对应检查解释的协议失败，属于严重失败，该场得分为 0。普通非基础检查失败可以保留部分质量分，`valid/legal=true`、`completed=false`，仍可参与同场质量与经核验的效率排名。基础/协议严重失败才是 `valid/legal=false`。缺失所选检查不能算通过。

同一场内将最高正原始分归一化为相对 100，是 UI/比赛层的排名规则。**相对 100 与 completed 是不同字段**；所有原始分均为 0 时不得给任何人满分。不同 scope_id 的成绩不可直接混榜。

前端分数始终是 **semantic_only**。语义适配器通过并不等于任意 HTML、浏览器交互、持久化下载、视觉、无障碍或整体产品已通过，`codex_review_required=true` 且完整前端分为 null。R/C 可以显示已完成的机器结果；其时耗、token 证据仍需独立核验。

未知错误、裁判 audit 失败、运行环境错误、取消和 host 超时都是待判状态 `valid/legal/completed=null`、`raw_score=null`，不能冒充候选失败分。候选在真实裁判中的可观察失败才记为失败。每个 case 的原始报告、命令和种子留在私有目录，公共摘要不包含种子。

## 效率与执行边界

`grade_match` 使用 `organizer.efficiency.score_efficiency`，未核验的指标保持 efficiency_score=null；source=API/host 字符串不能自动取得信任。无效候选的效率分可以按统一规则为 0，但这不表示指标已核验。全部指标必须是整个 Agent attempt 的累计量，不能用裁判运行秒数替代。

取消会在当前子进程运行期间检查，并停止其进程树，包括另开 session 的 worker；每个 case 都从提交副本重新运行。程序是本地可信代码工作流，不是恶意代码沙箱，正式外部选手应使用独立隔离环境。

验证：

```bash
python3 -m unittest arena.test_rules arena.test_judge -v
```
