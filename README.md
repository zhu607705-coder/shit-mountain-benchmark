# 屎山 Bug 挑战赛

**统一的 12 题 benchmark：推理 R1–R4、代码 C1–C4、前端 F1–F4。开放实现方法，固定行为目标，用实际结果比较。**

[GitHub 仓库](https://github.com/zhu607705-coder/shit-mountain-benchmark) · [Actions 一键验收](https://github.com/zhu607705-coder/shit-mountain-benchmark/actions/workflows/verify.yml) · [实测结果](results/VERIFICATION.md) · [审查与适配记录](imports/REVIEW.md)

## 拉取与一键测试

```bash
git clone https://github.com/zhu607705-coder/shit-mountain-benchmark.git
cd shit-mountain-benchmark
./scripts/test.sh
```

需要 Python 3.10+、Node.js 22+；无 pip/npm 安装步骤。`make test` 等价。仓库公开，可直接拉取。

这一命令运行裁判回归、API mock、前端状态逻辑、全部程序基线，以及真实 HTTP/SQLite/worker 环境；也确认故障起点仍能被检测出来。**不调用付费模型 API，不替代原生浏览器验收或人工盲评。** 输出在 `reports/` 和 `results/`。

GitHub Actions 配置了 Linux/Python 3.12 与 macOS/Python 3.14，支持 push、PR、手动 **Run workflow**。每次运行的 JSON 证据可从 Artifacts 下载。`main` 已配置上述两项必需检查、线性历史、禁止强推和删除；分支保护模板位于 `.github/branch-protection.template.json`。

## 题库

| 题号 | 任务 | 当前实际场景 | 主要交付 |
|---|---|---|---|
| [R1](reasoning/R1/PROMPT.md) | 相关扰动下的鲁棒调度 | 48 任务、3 模式、24 情景、预算和地区覆盖权衡 | 决策 JSON |
| [R2](reasoning/R2/PROMPT.md) | 有副作用的主动诊断 | 18 实验、11 干预、180 潜在世界 | 自适应策略树 JSON |
| [R3](reasoning/R3/PROMPT.md) | 八次探针，修什么才划算 | 10 组件、56 假设、20 探针、90 次事故回放 | 可执行策略模块 |
| [R4](reasoning/R4/PROMPT.md) | 在线调度与设备故障 | 20 场景，每场景 60 任务、6 设备 | 只读当前观测的策略模块 |
| [C1](code/C1/PROMPT.md) | 多租户异步账本服务维修 | HTTP、SQLite、独立 worker、7 类环境 | 完整仓库、定位报告、补丁、自测 |
| [C2](code/C2/PROMPT.md) | 持久化构建平台维修 | 项目/任务/快照/取消/恢复、11 类环境 | 完整仓库、定位报告、补丁、自测 |
| [C3](code/C3/PROMPT.md) | 强杀后的事务与日志恢复 | 原子事务、幂等、快照、压缩、I/O 故障 | 存储实现、故障回归测试 |
| [C4](code/C4/PROMPT.md) | 长期变化中的缓存一致性 | 内容键、依赖顺序、共享缓存、并发发布 | 构建器实现、变更与回归测试 |
| [F1](frontend/F1/PROMPT.md) | 凌晨事故控制台 | 10,000 事件、虚拟列表、因果调查、跨窗确认 | 可操作页面 |
| [F2](frontend/F2/PROMPT.md) | 实验排程账本 | 依赖、资源冲突、离线、撤销、三方合并 | 可操作页面 |
| [F3](frontend/F3/PROMPT.md) | 持续变化的事故工作台 | 50,000 记录、乱序版本、暂停、删除、导出 | 可操作页面 |
| [F4](frontend/F4/PROMPT.md) | 多窗口离线排程 | 字段合并、补偿撤销、导入、永久删除墓碑 | 可操作页面 |

所有题统一登记在 [benchmark.json](benchmark.json)。来源与修订只在维护者审计材料中追溯，不另分来源赛道或排行榜。

## 代码题怎样考查工程能力

C1/C2 从 `repository/buggy/` 起步，验收实际启动服务与独立 worker，使用真实 HTTP、SQLite、不同配置/路径、迁移、终止与重启。核心回归调用服务实际使用的同一份引擎。提交包含 `DIAGNOSIS.md`、完整补丁、可执行自测和 `TEST_REPORT.md`，保留“复现 → 定位 → 修改 → 自测 → 整体回归”的证据。

C3/C4 深入事务耐久性和缓存一致性机制，使用 `starter/` 起点；各题同时提供故障基线、修复基线、独立裁判和已复现的新增回归。高压规格和当前已运行的小规模检查分开记录。

[仓库赛道协议](organizer/REPO_TRACK_PROTOCOL.md) 解释定位、自测与整体回归的验收方式。故障起点是比赛资产；不要在维护题库时无意修掉它们。

## 统一计分

每题先得到合格性、原始指标和质量 Q；本轮合格最佳为 Qbest，相对分 **S = 100 × Q / Qbest**。没有正的合格 Q 时全员 0；同分并列。每个赛道四题等权，总分十二题等权，缺交为 0，待评为 null。

例如 Q 为 80、64、40，得到 100、80、50。100 表示该轮最佳，不是理论最优。只有一个作者基线时，归一化 100 不构成模型能力比较。

- R1/R2 使用题面固定收益/风险公式；R3/R4 使用 `100/(1+objective_loss/10)`。
- C1/C2 为环境 70 + 核心回归 20 + 自测有效性 10。未核验部分保持 null，并单列已验证小计。
- C3/C4 当前公布机制检查与计时原始量，完整性能负载和权重未冻结，完整 Q 保持 null。
- 前端功能/可访问/性能/设计指标按各题公开 rubric 执行；没有独立设计盲评时不补造总分。参考页面专用 smoke 不能代替自由布局作品的通用验收。

详细见 [比赛规则](organizer/COMPETITION_RULES.md)。未开展多模型难度校准、正式隐藏评测或独立前端盲评，不发布虚构总榜。

## 接口接入与提交导入

```bash
# 导入接口配置：配置只保存密钥的环境变量名称
python3 integrations/cli.py import-config --source integrations/config.example.json --output .local/model.json
python3 integrations/cli.py inspect --config .local/model.json

# 导出公开任务工作区，不包含参考解和组织者裁判
python3 integrations/cli.py export-task --task C1 --output workspaces/C1

# 导入外部 Agent 完成的目录或 ZIP，不在导入时执行代码
python3 integrations/cli.py import-submission --task C1 --alias model-v1 --source path/to/completed-submission

# 对明确允许在本机执行的提交评测
python3 scripts/evaluate_submission.py --task C1 --submission path/to/completed-submission --model model-v1 --output reports/model-v1-C1.json
```

R1/R2 可用 OpenAI-compatible Chat Completions 生成决策 JSON 并自动交裁判；密钥从 `BENCHMARK_API_KEY` 等配置指定环境变量读取。R3/R4、代码、前端使用具备文件/环境交互能力的外部 Agent 工作区。单次聊天调用不等同于完成仓库 Agent。

[接口文档](integrations/README.md) 给出完整命令、模型 API 的限制和离线 mock 证据。导入只做验证与复制，拒绝路径穿越、符号链接、异常压缩与覆盖；这不等于不可信代码执行沙箱。

## 查看页面与打包

```bash
make preview
# 打开 http://127.0.0.1:8769/frontend/F1/baseline.html
# 其它题改为 F2、F3、F4

python3 run_baselines.py
python3 organizer/leaderboard.py results/baseline_records.json --output reports/relative-score-demo.json
python3 organizer/package_release.py
python3 organizer/export_contestants.py
```

主办方包包含裁判、修复基线和证据；参赛包通过白名单从公开题面与故障起点生成。正式比赛不能把整个主办方仓库提供给参赛模型，即使以只读方式挂载。

当前数据均为合成数据。本地可信评测、公开有限矩阵与真正隔离的线上比赛是不同完成状态；详见 [验证报告](results/VERIFICATION.md)。
