# v0.2 Extreme：难度证据与边界

12题仍是一套统一题库。版本升级由用户要求驱动：每题至少10倍的实际负载/状态空间维度，再加入跨阶段依赖与新信息结构。数字倍数不等于认知难度倍数；没有证据能预先保证本模型或任何模型一定做不出来。

## 本次独立full复跑

命令：`python3 scripts/extreme.py --task all --scale full --seed 260926 --timeout 900 --output reports/extreme-full-v02`。完整结果已保存到 `results/extreme-v02/`。默认seed公开，仅用于复现，不能作为隐藏集。

| 题目 | 实际generated/executed规模 | 参考实现结果 |
|---|---|---|
| R1 | jobs_per_episode=576（12×，executed） | 合法；Q=35.3684 |
| R2 | evaluated_worlds=1800（10×，executed）；distinct_available_tests=180（10×，generated） | 合法；Q=46.9417 |
| R3 | components=128（12.8×，generated）；episodes=960（10.7×，executed） | 合法；Q=25.0891 |
| R4 | jobs_per_episode=720（12×，executed）；machines=24（4×，generated） | 合法；Q=23.0764 |
| C1 | tenants=20（10×，generated）；http_concurrency=80（10×，executed）；workers=20（10×，executed） | 完整v2不合格，Q=0；旧实现缺必需stage接口，旧接口压力结果另列 |
| C2 | nodes=5000（10×，executed）；depth=2000（10×，executed） | 完整v2不合格，Q=0；旧实现缺必需stage接口，旧接口压力结果另列 |
| C3 | fault_histories=288（72×，executed）；transactions=1440（7.2×，executed） | 完整v2不合格，Q=0；旧实现缺必需stage接口，旧接口压力结果另列 |
| C4 | roots=20（10×，executed）；mutations=1000（10×，executed） | 完整v2不合格，Q=0；旧实现缺必需stage接口，旧接口压力结果另列 |
| F1 | initial_records=100000（10×，generated）；initial_records_acknowledged_by_adapter=100000（10×，executed） | 新弱语义适配器 3/8；完整UI/视觉未评分 |
| F2 | initial_records=1200（100×，generated）；initial_records_acknowledged_by_adapter=1200（100×，executed） | 新弱语义适配器 5/47；完整UI/视觉未评分 |
| F3 | initial_records=500000（10×，generated）；initial_records_acknowledged_by_adapter=500000（10×，executed） | 新弱语义适配器 4/8；完整UI/视觉未评分 |
| F4 | initial_records=1200（100×，generated）；initial_records_acknowledged_by_adapter=1200（100×，executed） | 新弱语义适配器 5/49；完整UI/视觉未评分 |

C1实际生成128,000事件，但大并发中出现HTTP500/SQLite锁错误，不能称为处理完所有full事件。C2/C4的旧实现深图错误属于规模/递归边界，不能单独证明深推理难度。C3的原接口扩大层仍然全部正确，这一通过被保留；它仍缺新版必需的writer-generation协议。

## 超过简单放大的机制证据

- R1小实例独立枚举：先投资的损失5，不投资的最佳损失51.6667。
- R2先做没有即时信息的准备再测量，损失0.6；直接修复损失31。
- R3单个互补探针Bayes错误率0.5，两步0.15，加入校准三步0；不是简单增加字符串长度。
- R4两个首选都合法，先抢高权重任务损失143.608，先做低权重耗材链为117.91。
- C1逻辑幂等不能跟随物理epoch重置：新故障starter单机制通过，丢ACK加迁移重试时重复转账。
- C2局部取消与局部改图均通过，但取消旧图的恢复槽被新图复用后发布旧值。
- C3旧压缩准备后换writer，新增ACK/删除再遇迟到发布会丢数据并复活删除。
- C4旧源与新环境各自合法，混合后却不属于任何一致manifest，并污染缓存。
- 前端使用独立小见证检查因果与并发、observed-remove、恢复代际、原子回滚和24种递送排列。全量trace还要求身份/焦点/历史、暂停快照、墓碑GC与导出一致。

四个代码stage的候选入口和公开协议真实参与资格判定，不是仅附在报告里的演示。故障starter与已知可行小witness用于验证裁判；我们没有提供完整高难解，更没有把缺接口伪装成一次真实模型解题失败。

## 验证与未验证

已独立重跑：推理12项、代码10项、前端8项裁判/见证回归，以及12题smoke和full构造/执行。前端full是语义适配器进程的实际回放，不是500k行真实浏览器压力。

原生浏览器额外打开F4轨迹查看器并读取smoke样本：27条命令、36初始记录、194次递送、5个窗口标识；控制台无错误。它只是公开输入查看器，不是参赛UI或完整前端验收。

尚未开展多个真实商业模型的独立解题校准、正式隐藏轮次、极限浏览器长压、完整无障碍与盲评。参考策略、旧实现能力缺口、新故障起点和真实模型能力必须分开解释。

## 与实验记录衔接

`experiments/README.md`负责多提示词多轮分派、答案沉淀和封存，`GRADER_README.md`负责Codex独立评分。质量和效率分分开；模型解题耗时/token来自独立host/API证据，以上Python裁判用时不冒充模型思考时间。

## 统一启动器的实际验收

Arena 的 27 项回归覆盖六档范围、抽签承诺、封存和篡改拒绝、取消与成绩发布、首次正式分冻结、环境错误重试、中文路径启动、单进程复用及独立效率证据绑定导入。额外的原生浏览器流程实际执行了 R3 青铜抽签、查看三个不同范围的提示段、读取 README、封存两个策略并在后台调用真实裁判。

空操作策略得到原始质量 20.8333，整组修复策略得到 28.7356，同场相对分分别为 72.5 与 100；两者都是流程验收控制，不是模型性能结果。缺少独立模型消耗证据时，效率分保持待核验。390px 窄屏在初始页和成绩页均未出现页面横向溢出，控制台没有 error。记录见 `results/extreme-v02/arena-browser-verification.json`。

UI 采用锁定版本的官方 Lucide SVG，来源清单与许可随仓库保存。详细说明收进可展开区域和 README。六档是预先冻结的任务规格，推荐档位仍待真实多模型试验校准。
