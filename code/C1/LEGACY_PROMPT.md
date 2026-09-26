# C1 v0.2：数据库还在，账却不动了——真实仓库故障修复赛

你接手一个完整可运行的 Python 标准库服务：**HTTP API → SQLite 持久队列/事件表 → 独立后台 worker → 持久化查询投影**。事故症状包括旧库升级后任务停滞、API/worker 从不同目录启动后分库、worker 中断后任务卡死，以及跨租户并发冲突。

从 `repository/buggy/` 完整 starter 开始，复现、定位、修复并编写自己的回归测试，证明启动到重启恢复全流程可用。允许重构内部设计，保留公开接口和诊断适配接口；没有唯一补丁、数据结构或最优实现。

## 开始运行

在本题目录运行：

```sh
cp -R repository/buggy my_submission
python3 -B e2e_env_judge.py --submission my_submission --output my_before.json
python3 -B judge.py --submission my_submission
```

手动运行时，在两个独立终端进入提交目录，分别执行：

```sh
LEDGER_DB=runtime/ledger.sqlite3 LEDGER_PORT=8765 python3 manage.py serve
LEDGER_DB=runtime/ledger.sqlite3 python3 manage.py worker
```

API 和 worker 必须是实际独立进程，共用持久 SQLite；禁止以内存 mock 或请求内同步计算取代后台流程。无外部依赖，不要求 Docker。`manage.py init` 应可单独初始化或迁移数据库。

## 冻结的业务接口

| HTTP 接口 | 要求 |
|---|---|
| GET /health | 200，status=ok、schema_version=2，对应已初始化的当前库 |
| POST /v1/batches | JSON tenant/request_id/events；202返回job_id/duplicate |
| GET /v1/jobs/<id>?tenant=A | 本租户任务的id/tenant/request_id/status；其他租户查询404 |
| GET /v1/jobs?tenant=A | jobs列表，只含该租户，按任务ID升序 |
| GET /v1/tenants/A/state | tenant/generation/balances/statuses；完成后可观察，重启后保留 |
| GET /v1/stats?tenant=A | tenant/jobs/done/event_variants，统计值为整数 |

每批最多200个事件、HTTP JSON最多1,000,000 bytes。核心业务语义完整冻结于 `CORE_CONTRACT.md`：租户身份、载荷冲突、重复、逆序撤销、整数精度与原子业务校验都仍适用。服务先验证非空tenant/request_id、事件列表和envelope。某事件tenant与批次不符则整批400且不落库；不平衡post等业务错误仍被接收，最终由核心标记INVALID。

`(tenant,request_id)` 是请求幂等键：完整事件列表的规范JSON相同，重放返回原job_id且不新增任务；同键不同内容409。不同租户可重复使用request_id/event_id。每个规范事件载荷只持久保留一次；不得最后写覆盖冲突证据。任务与事件同事务接收。

任务状态为pending→processing→done。worker在事务内领取；领取者退出后，新worker必须在租约过期后回收任务。旧worker恢复后不得提交过期领取的成果。完成状态与查询投影同事务提交。未完成时可读到旧投影；全部任务完成时等于该租户全部已接收事件的完整核心投影。generation为已处理任务ID的单调不减水位，不要求连续。

## 环境与迁移

`LEDGER_DB` 默认runtime/ledger.sqlite3；相对路径必须相对manage.py所在仓库解析，绝对路径原样使用，不依赖cwd。自动建立父目录，支持非ASCII/空格。API和worker从不同cwd启动必须使用同一库。

其他环境变量：LEDGER_HOST、LEDGER_PORT、LEDGER_WORKER_POLL、LEDGER_LEASE_SECONDS、LEDGER_WORKER_DELAY。最后一项是公开故障注入点，领取后、完成事务前暂停指定秒数，不能删除。评测给定合法正数配置。

支持fresh v0、当前v2，以及公开 `e2e_env_judge.py:make_legacy` 定义的旧v1 schema。旧库无claimed_at，jobs.request_id与events.event_id只有全局唯一约束。迁移必须原子保留旧任务ID/状态/事件并重建约束；禁止清库或只改版本号。旧JSON空白/字段顺序可能不同，迁移后旧请求重放仍幂等。v1内容保证可解析为合法JSON。

保留诊断适配函数，供公开变异测试使用：config.database_path(value)、db.connect(path)（上下文管理器yield SQLite connection）、db.initialize(path)、service.validate_batch(tenant,request_id,events)、service.submit_batch(path,tenant,request_id,events)、service.get_job(path,id,tenant)、worker.claim_job(path,lease)、worker.process_once(path,lease,delay=0)。内部算法可以重构。HTTP worker与核心回归必须调用同一提交目录中的engine.py:solve(events)。

## 评分：环境70 + 回归20 + 自测10

端到端裁判将提交复制到临时目录，选择空闲端口和临时DB，真实启动API/worker，通过HTTP验证7项，每项10分。每项启动/任务等待上限1.2秒，HTTP请求超时0.4秒；结束后终止回收其启动的进程、删除临时目录。

1. 默认完整流程：健康、接收、完成、结果、列表、统计、跨租户读取拒绝、非法批次、请求冲突。
2. v1迁移、历史保留、旧请求重放、升级后跨租户同名请求。
3. 非ASCII/空格目录，API/worker不同cwd。
4. 领取后强制杀死worker，再启动新worker恢复。
5. 重复请求、撤销先到、后到冲突载荷。
6. 8路HTTP并发、2个worker、2个租户复用请求ID与事件ID。
7. API和worker全部重启后的查询持久性和幂等重放。

回归20分=`20×judge.py --submission <同一仓库> 的63项通过率`，不使用旧核心计时奖励。

自测10分来自提交者的 `test_submission.py`。正向clean运行必须退出成功且实际发现至少1个测试，才进行5个负向变异：跨租户任务泄漏、cwd依赖路径、processing不回收、接受混租户批次、迁移丢历史。每个独立临时副本/新Python进程，0.9秒超时，每杀死一个2分；bootstrap失败不算杀死，永远失败拿0分。变异只在子进程内替换相应诊断函数，不改持久源码。

这些分数只表示对5种公开缺陷的检测力，不代表完整自测质量或未知缺陷覆盖。可以阅读公开测试来定位；测试不得侦测mutation名称/裁判状态后故意退出，正式收分需审查其真实性。

致命门槛为default_flow、concurrent_isolation、restart_persistence，任一失败valid=false，不进入有效榜单但保留诊断分；其他失败逐项扣分。raw_score为70/20/10三项之和。当前公开矩阵全通过可以得到100，不能据此宣称工程最优或隐藏集满分。

## 交付证据

提交完整修复仓库、自己的test_submission.py、DIAGNOSIS.md和TEST_REPORT.md。诊断记录需含修改前复现命令、实际失败/日志、根因、跨模块影响和修复理由；测试报告需含修改前后相同命令的实测、新增自测和未验证边界。可另附DESIGN.md解释迁移/租约/事务不变量。文档供审查，不虚构额外主观分。

允许阅读公开fixture、题面、评测器。禁止运行时读取oracle/基线答案、硬编码样例、访问主办方隐藏集或修改裁判。本工具是真实本机进程与localhost HTTP，未实现不可信代码安全隔离。正式线上赛应再加独立容器/用户、禁外网、资源上限和只读评测挂载。
