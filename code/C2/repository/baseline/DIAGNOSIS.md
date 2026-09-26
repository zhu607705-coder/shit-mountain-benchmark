# 基线诊断与修复证据

这是对挑战赛合成缺陷的参考修复；不是生产事件归因。公开复现使用 C2 根目录的 `python3 e2e_env_judge.py --submission repository/buggy`。结果存 `repository_buggy_result.json`，8/11项失败；随后对baseline相同矩阵全部通过。

| 症状与最小复现路径 | 根因与涉及模块 | 基线修改与复核 |
|---|---|---|
| 配置 `/build/v2` 后GET health为404 | config读了过时的api_prefix键，与配置文件base_path不一致 | 统一base_path并去除末尾斜杠；configured_base_path通过 |
| web/worker不同cwd，作业永久pending | 相对database以各进程cwd解释，写入两个不同SQLite文件 | 相对配置文件目录解析并规范绝对路径；different_process_workdirs通过 |
| A/B项目同目标名返回串台；跨项目job URL可读 | core共享缓存跨实例；service.get_job查询只按job ID | core使用独立缓存，SQL同时约束job与project；project_isolation通过 |
| running任务确认取消后仍变done | 只检查status，未处理cancel_requested；成功发布覆盖取消 | worker准备阶段检查取消位；发布事务再次检查，取消优先；cancel_running_then_retry通过 |
| 作业入队后改图，旧作业按新图算 | runner重新读取当前projects.graph，忽略入队payload | 用持久化快照执行，按项目+快照管理engine；enqueue_snapshot_isolation通过 |
| 强杀worker后任务永远running | recover只处理过时的queued状态 | 启动恢复running为pending或cancelled；worker_crash_recovery通过 |
| v1数据库启动报payload不存在 | CREATE TABLE IF NOT EXISTS不能迁移已有表 | 事务中检查列、补revision/payload/cancel_requested、回填旧作业快照、更新schema版本；legacy_schema_migration通过 |
| 故障修复后得到成功空列表；图改动后取旧值 | core缓存身份、失效、异常清理及返回值所有权缺陷 | 复用已验证独立实例/版本戳/不可变值核心；同一仓库实现57/57回归，dependency_failure_then_repair通过 |

SQLite连接通过上下文管理关闭；初始化用BEGIN IMMEDIATE避免两个进程同时迁移。作业发布检查与状态写入在同一事务中，避免取消和成功发布的竞态。迁移保留项目图、旧作业与结果，不以删库代替修复。

自测补充了配置路径、basepath、快照、跨项目查询、取消发布、恢复、迁移和worker/core导出一致性。HTTP集成矩阵与模块自测用途不同：前者检查真实进程边界，后者帮助快速定位回归。selftest中临时目录路径比较使用resolve，兼容macOS /var到/private/var的符号链接。

已知边界：本版约定单worker；进程准备阶段可协作取消，计算结束前也会再次检查取消，但不是抢占式中断长Python运算。图快照变化时基线重建Engine，重复相同快照会复用缓存；仍有跨快照增量优化空间。当前通过公开矩阵不证明生产鲁棒性或隐藏泛化。
