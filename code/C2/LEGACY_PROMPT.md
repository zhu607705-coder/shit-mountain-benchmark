# C2：跨进程构建服务事故修复——从复现到全功能验收

你接手 `repository/buggy/` 这个可启动的合成工程：HTTP API 管理多个项目，SQLite 保存图和作业，独立 worker 进程领取任务，再调用增量依赖构建引擎。它在默认目录的一次简单请求中能工作，但更换环境、修改图、取消任务、重启和升级已有数据库时会产生相互关联的错误。先读 `INCIDENT.md`。

**完成要求：自己启动服务和 worker，复现症状、定位跨模块根因、修改仓库、编写并运行自测，最后证明整个业务闭环在环境矩阵中仍然可用。** 只交一段解释、一个孤立函数或单个测试通过不算完成。允许重构、调整缓存与状态组织，不预设唯一补丁或最优架构。

## 项目与启动

仅依赖 Python 3.10+ 标准库，不需要 Docker、数据库服务或第三方包。

```text
repository/buggy/
  cli.py, example_config.json, engine.py
  app/config.py       配置与数据路径
  app/api.py          HTTP路由
  app/service.py      项目、作业与事务边界
  app/db.py           SQLite schema、迁移和状态恢复
  app/runner.py       独立worker、领取、取消、发布结果
  app/core/           原有图引擎、缓存和向量运算
```

在 C2 目录开两个终端。可以把 buggy 复制到自己的提交目录再运行：

```bash
python3 repository/buggy/cli.py serve --config repository/buggy/example_config.json
python3 repository/buggy/cli.py worker --config repository/buggy/example_config.json
```

服务器向 stdout 输出实际监听端口；配置 `port: 0` 由系统分配空闲端口。两进程共用同一个配置文件，允许工作目录不同。`database` 为相对路径时必须相对**配置文件所在目录**解释；示例 base path 是 `/build/v2`。调试期可在配置里指定自己的空闲端口，验收不依赖固定端口。

## 必须保留的服务契约

| 方法与路径（加配置base path） | 行为 |
|---|---|
| `GET /health` | 服务已就绪，返回 `{"ok":true,"schema":2}` |
| `POST /projects/{id}` | 创建或完整更新项目图，body为 `{"nodes":...,"aliases":...}` |
| `POST /projects/{id}/graph` | 同上，增加图revision |
| `POST /projects/{id}/jobs` | body为 `{"target":"main"}`；持久化当前图快照，返回job ID |
| `GET /projects/{id}/jobs/{job}` | 仅能读取该项目的作业；其他项目或未知ID返回404 |
| `POST /projects/{id}/jobs/{job}/cancel` | 取消pending/running作业；已终止作业保持原状 |

作业状态为 `pending → running → done / failed / cancelled`。成功结果为 `{"value":[...]}`；依赖错误必须保存为failed与错误码，不能伪装成功空向量。入队后修改项目图不改变已排队作业的图快照；新作业使用新图。外部取消必须在发布成功结果前再次检查，已确认的取消不能被晚到成功覆盖。worker中断后，重新启动必须恢复未完成作业；本版部署约定为**一个worker进程**，不要求多worker租约协议。

服务重启必须保留已完成结果和项目图。已有v1数据库缺少项目revision、作业payload和cancel_requested列；要原地升级为v2并保留已有项目/作业，旧pending作业按它所属项目的现有图补齐快照。迁移后重复启动必须仍正常。HTTP与worker均可能先启动，因此初始化需避免迁移竞争。

配置包括 `database`、`base_path`、`port`、`job_delay`。最后一个参数是合成执行准备阶段的持续秒数，便于稳定复现取消与进程中断；准备阶段应响应取消。完整图引擎语义与输入范围见 `CORE_CONTRACT.md`，其中图修改、别名、环、取消、错误顺序、返回值所有权都必须兼容。

仓库根 `engine.py` 导出的 `Engine` 必须与实际worker使用的是同一份实现。不得让服务调用另一套代码，同时用裁判特供实现通过核心回归。

## 提交物与工作证据

提交整个修复仓库，至少包含：

1. `DIAGNOSIS.md`：每个根因的复现命令、预期/实际现象、状态或日志证据、涉及模块，以及修复策略。
2. 可应用的补丁或清晰的git diff；项目仍能按上述命令启动。
3. 可运行的 `selftest.py` 或等价测试入口，测试真实行为与跨模块不变量。
4. `TEST_REPORT.md`：按“复现 → 修改后自测 → 全回归”报告实际命令、结果、未解决项。只写“应该通过”不得分。

可以阅读公开测试和fixture来定位，也可以新增自己设计的病例。不能修改主办方裁判、硬编码fixture/测试名称/预期答案、读取封存隐藏集或隐藏期望答案。官方baseline只用于提交冻结后比较；正式赛把它与参赛环境隔离。服务合理的HTTP、SQLite、文件与子进程操作属于题目本身。

## 评分与全功能验收

- **环境业务验收70分**：11项真实HTTP/独立进程/临时SQLite矩阵，按通过比例计分。涵盖默认闭环、非默认base path、不同工作目录、非ASCII目录、项目隔离、运行中取消再试、故障修复、快照、服务重启、worker中断恢复、旧schema迁移。
- **核心整体回归20分**：原图引擎57例通过率乘20；必须对同一提交目录执行。资源门槛与原核心致命用例仍生效。旧核心原分保留为诊断数据，不再直接当作仓库题总分。
- **新增自测质量10分**：主办方检查提交方测试，按5个明确锚点各0/1/2分：能复现至少一个原始bug；断言关键状态/返回值而非只看进程存活；覆盖至少一处跨模块或跨环境关系；包含取消/失败/重启之一的恢复路径；可独立复跑且报告与实测一致。0=缺失，1=部分，2=有可复核运行证据。没有人工核验前为 `null`，禁止自给满分。

环境致命门槛为默认闭环、项目隔离、重启持久化和旧schema迁移；任一失败则环境 `valid=false`。最终有效性同时要求环境门槛与核心门槛。未评完自测质量时，只报告环境加核心的已验证机器小计，完整 `raw_score=null`，暂不进入正式相对归一化。

```bash
python3 e2e_env_judge.py --submission /absolute/path/to/your_repository
python3 judge.py --submission /absolute/path/to/your_repository
python3 /absolute/path/to/your_repository/selftest.py
```

所有实例是公开合成开发环境；该本地执行器会运行提交代码，**不是不可信代码安全沙箱**。正式公开赛需要外部隔离与独立封存测试。本包没有把当前固定公开矩阵宣称为生产可用性证明。
