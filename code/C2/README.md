# C2 仓库事故挑战：HTTP构建服务、SQLite与独立worker

当前主任务是 `PROMPT.md` 中的**可启动仓库修复**。从 `repository/buggy/` 与 `INCIDENT.md` 开始，完成复现、定位、修改、自测及整体回归。原 `buggy/`、`baseline/` 和 `judge.py` 保留为核心引擎回归资料，不能代替仓库任务。

本仓库全部为原创合成测试项目，Python 3.10+ 标准库即可运行。HTTP和worker是两个真实子进程，数据保存在真实SQLite中；无Docker、固定端口或外部服务要求。

## 一键业务验收

在本目录执行，下列命令会自动创建临时配置与数据库、启动服务器和worker、发送真实HTTP请求、杀死/重启进程并清理现场：

```bash
python3 e2e_env_judge.py --submission repository/buggy --output repository_buggy_result.json
python3 e2e_env_judge.py --submission repository/baseline --output repository_baseline_result.json
```

随后用**同一份仓库实现**跑核心回归和提交方自测：

```bash
python3 judge.py --submission repository/baseline --output repository_core_baseline_result.json
python3 repository/baseline/selftest.py
python3 -m unittest -v test_harness.py
```

仓库根 `engine.py` 只导出 `app.core.engine.Engine`；worker也导入这一类。不会用旧目录的基线替代实际服务实现评分。

## 手动启动与实际请求

两个终端分别运行：

```bash
python3 repository/baseline/cli.py serve --config repository/baseline/example_config.json
python3 repository/baseline/cli.py worker --config repository/baseline/example_config.json
```

服务器第一行JSON给出动态端口。把它填入下面 `PORT`，即可走创建项目、提交作业的真实接口：

```bash
PORT=填入服务器输出的端口
curl -s "http://127.0.0.1:${PORT}/build/v2/health"
curl -s -X POST "http://127.0.0.1:${PORT}/build/v2/projects/demo" -H 'Content-Type: application/json' -d '{"nodes":{"a":{"op":"input","data":[2,4]},"root":{"op":"scale","deps":["a"],"factor":3}},"aliases":{"main":"root"}}'
curl -s -X POST "http://127.0.0.1:${PORT}/build/v2/projects/demo/jobs" -H 'Content-Type: application/json' -d '{"target":"main"}'
```

最后一次返回作业ID。`GET /build/v2/projects/demo/jobs/{id}` 可以轮询；成功时result应为 `{"value":[6,12]}`。Ctrl-C分别结束两个进程。示例数据库位于配置文件旁的 `state/`，保留它可手动验证重启持久化。不要删除真实待迁移数据库来掩盖错误。

## 已实跑结果与评分边界

| 项目 | buggy | 本包baseline |
|---|---:|---:|
| 真实环境矩阵 | 3 / 11 | **11 / 11** |
| 环境分（70分） | 19.090909 | **70** |
| 环境valid | false | true |
| 同份仓库核心回归 | 2 / 57 | **57 / 57** |
| 核心换算分（20分） | 0.701754 | **20** |
| 提交方自测实际运行 | 起点未提供 | **8 / 8通过** |
| 自测质量（10分） | 未评 | **null，待主办方按锚点核验** |
| 完整raw_score | null | **null** |

本包baseline已验证机器小计为 **90 / 90**，不等于完整总分、更不等于比赛当轮最佳。原核心judge自己的80+资源分保留用于诊断；仓库题只取其正确率乘20，避免重复加分。若继续举办性能赛，可另行冻结资源指标，本版没有暗中改变权重。

结果文件：`repository_baseline_result.json`、`repository_buggy_result.json`、`repository_core_baseline_result.json`、`repository_core_buggy_result.json`、`repository_selftest_result.json`。基线诊断与复现证据在 `repository/baseline/DIAGNOSIS.md` 和 `TEST_REPORT.md`；可应用差异见 `repository_baseline.patch`。

环境门槛、11项矩阵、自测质量的5个0/1/2锚点见 `PROMPT.md`。公开测试可阅读和用于定位，不能将公开seed称为隐藏测试。该执行器是可信本地原型，并不隔离不可信提交代码。
