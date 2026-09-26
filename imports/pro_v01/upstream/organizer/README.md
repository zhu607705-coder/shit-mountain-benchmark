# 屎山 Bug 挑战赛 v0.1

三方向、六个开放解法任务。每题有中文题面、可替换接口或缺陷starter、作者基线及原始自检结果。

| 编号 | 方向 | 题目 | 优化对象 |
|---|---|---|---|
| R1 | 推理 | 八次检查，找出真正值得修的故障 | 信息获取与修复的总风险 |
| R2 | 推理 | 越救越堵的在线调度中心 | 截止期、资源、故障恢复 |
| C1 | 代码 | Kill -9 之后，客户的数据还在吗 | 耐久事务、快照、压缩与性能 |
| C2 | 代码 | 缓存命中 99%，发布产物却是旧的 | 构建正确性与增量效率 |
| F1 | 前端 | 首屏很漂亮，五万条实时记录一来就崩 | 交互、实时状态、性能与设计 |
| F2 | 前端 | 两个窗口同时离线，排程被谁改没了 | 协作、离线、撤销与交互设计 |

先阅读 RULES.md，再看 tasks/*/TASK.md。六题的高难扩展规格与本次已执行的小规模自检明确区分。BASELINE_REPORT.md 汇总实际结果。

## 运行 Python 基线

Python 3.11+，标准库；当前实测解释器为 Python 3.13.5。C1 使用 POSIX fcntl，原生 Windows 不适用，建议 Linux或macOS。

```bash
python organizer/run_core.py --task R1
python organizer/run_core.py --task R2
python organizer/run_core.py --task C1
python organizer/run_core.py --task C2
python organizer/scoring.py
```

这些脚本仅用于运行包内已知代码。不要直接用它加载不受信任的参赛代码，正式比赛需要隔离执行。

## 预览前端基线

```bash
python -m http.server 8000 --bind 127.0.0.1
```

浏览器打开本地服务对应的 tasks/F1_incident_console/baseline.html 或 tasks/F2_offline_planner/baseline.html。离线/多窗口功能应在同一HTTP origin测试，不建议直接双击file URL。

前端没有第三方网络依赖。starter.html 为含故障的起点，baseline.html 为本次功能基线。公开界面任务可重构布局，不以基线截图为唯一答案。

## 原生浏览器自检

```bash
python -m pip install playwright
python -m playwright install chromium
python organizer/check_frontend.py
```

脚本优先使用 CHROMIUM_PATH 环境变量，其次系统 chromium，否则使用Playwright安装的浏览器。当前环境运行原生模式受URL策略限制，未完成原生模式验证。不要移除环境安全策略来让测试通过。

包内已测模式为：

```bash
UI_TASKS=F1 python organizer/check_frontend_memory.py
UI_TASKS=F2 python organizer/check_frontend_memory.py
```

该模式在允许的 about:blank 页面执行DOM，显式模拟存储、导航、下载和窗口事件。结果中记录了这个边界。

## 发给参赛模型

使用单独的 contestant ZIP。它排除了 baseline.py、baseline.html、organizer/、results/ 和最优策略讨论。不要把主办方包整个上传给被测模型。

提交时保存最终代码、依赖与入口、外部工具轨迹、实际运行输出。参赛者无需提交私有思维链，也不用写长篇“我已经修好”的自评。

## 当前还不是完整线上benchmark

organizer/KNOWN_LIMITS.md 列出剩余覆盖问题。评分器独立部署、私有随机种子、大规模故障注入、设计盲评及正式公平预算试跑尚未完成。本包的价值是先让六题具备明确契约和真实可运行起点，而不是虚构六个已经完成压力验证的大型生产仓库。
