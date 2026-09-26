# C1–C4 extreme 实施与实际验证

这次增加两层：保持原接口的真实环境/压力回归，以及必须提交 `extreme.py` 的 stage-v2 新协议。旧基线没有扩展接口时明确记录 capability_gap，因此不能获得完整 extreme 资格；不会把接口缺失当成难度证据。

## 可运行入口

```bash
python3 -B code/extreme_selftest.py
python3 -B code/extreme.py --task C1 --scale smoke --seed 260926 --output result.json
python3 -B code/extreme.py --task C3 --scale full --seed 260926 --submission my_submission --output full.json
python3 -B code/extreme.py --task C4 --scale full --seed 260926 --export /tmp/c4-workspace
```

Python 3.10+、POSIX、标准库。C1/C2直接复制完整真实服务，C3/C4接受文件或目录；目录中的engine.py/baseline.py/store.py用于旧合约，extreme.py用于新协议。导出包含两个部分的可运行缺陷starter、启动说明、实际scenario、无答案的观察型smoke和完整协议；主办方裁判与oracle不会进入公开导出。

## 机制证据：单机制正确，组合后错误

每个 stage starter 都已经在真实 SQLite/文件上执行两个局部控制与组合轨迹；控制和首个组合使用相同seed，避免数据差异混入因果比较。完整证据在各题 `extreme/stage_audit.json`，其中扩展执行包含2项控制和12组组合。

| 题 | 局部控制 | 必需新组合 | 真实故障 |
|---|---|---|---|
| C1 | 丢失ACK后原地重试；单独迁移后转账 | 已提交丢ACK→物理epoch迁移→重开→逻辑请求重试 | 转账执行第二次，余额守恒仍成立，但逻辑请求幂等性已坏 |
| C2 | 取消后同图重试；成功后改图 | 取消已准备的旧图→更新图→重启→重试 | 旧恢复槽污染新图结果 |
| C3 | 单独压缩；单独writer迁移后写入 | 旧压缩准备→迁移→新ACK/删除→旧压缩迟到发布 | 新ACK丢失，已删除键复活；原子replace本身并不能救正确性 |
| C4 | 稳定manifest；更新完成后再build | 采集旧源→manifest更新→环境与缓存发布→旧manifest重放 | 返回旧源+新环境的混合cut，并将其缓存 |

这些是机制存在、judge可以检出的证据，不是“所有模型都无法解出”的保证。新协议刻意很小，便于审计状态机；它们需与原真实服务/存储/构建环境共同通过，不能以单独补一个小适配器代替完整系统验收。微型可行witness是独立有限状态计算，不宣称提供了完整高性能极难解。

## full 已运行结果

`code/C*/extreme/baseline_full.json` 保存旧参考实现的完整机器输出。本机并行执行的时间仅供复现诊断，不用于横向速度排名。

| 题 | 实际构造或执行的扩大维度 | 原接口扩大层结果 | 新协议状态 |
|---|---|---|---|
| C1 | 生成20租户/1,600逻辑批次/128,000事件；实际启动20worker并以80线程发请求 | 迁移、ACK/租约链通过；完成2,300请求计数后遇HTTP500，日志明确为 `BEGIN IMMEDIATE` 的 `sqlite3.OperationalError: database is locked`；未完成全部full轮次 | 旧基线缺接口；独立故障starter组合失败 |
| C2 | 实际400个入队快照、20项目、5,000节点/2,000深度 | 快照/取消/恢复链通过；深图经真实HTTP/worker返回RecursionError | 旧基线缺接口；独立故障starter组合失败 |
| C3 | 实际100,000键、1,440交易、8快照线程、288切点历史 | 289/289扩大层检查通过，包括重开幂等、写锁和全部故障注入 | 旧基线缺接口；独立故障starter组合失败 |
| C4 | 实际20root、1,000变更、12发布进程、5,000节点/2,200深度 | 缓存历史和并发发布链通过；深图RecursionError | 旧基线缺接口；独立故障starter组合失败 |

明确的10倍轴：C1租户2→20、worker2→20、并发线程8→80；C2节点500→5000、深度200→2000；C3公开故障实例4→288（新增故障类型，非同分布难度倍数）；C4共享root2→20、历史变更100→1000。C3交易200→1440只有7.2倍，报告不把它写成10倍。生成、执行尝试与全部成功分开记录。

## 裁判验证与边界

`extreme_selftest.py` 覆盖手算微型oracle、依赖顺序/重复、full物化计数、C3不同持久历史、错误产物负控、坏Store的行为失败/注入能力缺口区分、导出包不含host裁判/oracle且脱离checkout后启动、四个新stage局部控制/组合反例、候选扩展真正参与判分，另加入模拟全部必需检查通过时Q=100、任一失败时Q=0以及裁判耗时不改变Q的正向评分见证，共10项。

`audit_passed` 表示裁判控制例与反例通过审计；`candidate_result.valid` 才是候选资格。v0.2的机器合约质量Q=100当且仅当旧接口扩大层与必需stage全部通过，否则Q=0；同时输出raw_score与quality_score。诊断通过率不充当完整成绩。正确实现的Agent耗时和token效率由独立host记录和计算，裁判运行时间不能当成模型思考时间；没有恢复未标定的旧性能奖励。smoke分数只对当前调试子集成立，正式比较采用冻结full轮次。

压力实跑曾发现10万键通过命令行JSON传递超过OS argv限制。这是裁判错误，已改为临时参数文件并重新完成full运行，未计为候选失败。C3故障拦截仅针对Python os.write/fsync/replace，绕过者标capability_gap；SIGKILL不是模拟存储设备断电。执行器回收本次进程组和临时目录，但不是不可信代码沙箱。没有新增第三方依赖或修改旧题实现/合约。
