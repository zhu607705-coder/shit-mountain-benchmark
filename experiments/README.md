# 让 Agent 读题实验，答案先封存，再由 Codex 独立评分

这个入口把出题、答题、封存和评分拆成可复核的步骤。**每次试验产出真实文件并保存指纹；Agent 自己说“通过”不构成评分。** 默认计划为 12 题 × 3 种提示词 × 3 轮，即 108 次独立尝试。不会预先复制 108 份大数据：每题公共输入只导出一份，每次尝试仅有独立目录和说明，开始答题时再复制必要的工作文件。

该入口不调用模型 API、不读取 API Key、不自动创建 Codex 任务。你可以把准备好的公共目录交给任意能够读文件、改代码和测试的 Agent；每个 attempt 应使用新会话，避免前一次答案污染另一种提示词或轮次。

## 准备实验

```bash
python3 scripts/experiment.py prepare \
  --plan experiments/plan.example.json \
  --output workspaces/experiments/extreme-v02-study-001
```

示例 `plan.example.json` 包含题目、三种提示词、轮数、smoke/full 与预算声明。首次试跑可复制为临时计划，只保留 R3、一种提示词、一轮，并设 `scale=smoke`。每次 prepare 必须使用新的实验 id 和目录；不会覆盖已有实验。

对比多个模型时，在它们的计划中填写相同的可选 `cohort_id`，例如 `"cohort_id": "extreme-v02-comparison-a"`，但为各模型使用不同的实验 `id` 和输出目录。同一 cohort 复用同任务、同轮次的私有评分 seed，提示词、任务、轮数、scale、预算、效率策略、公共题包和生成器源码指纹必须一致；不一致会拒绝 prepare，不会改写原 cohort。私有 cohort 文件只保存在 `reports/experiments/cohorts/`，使用独占锁与原子写入；忙锁不被接管。公共工作区只得到 cohort ID 与不透明的 `comparison_id`，没有私有种子。

`comparison_id` 由实验设计、公共题包指纹、生成器源码指纹和私有 seed 集合共同计算，不包含实验 id。因此同 cohort 下不同模型的实验可以共享比较身份；未指定 cohort 的实验各自生成新案例，仍可独立完成，但比较身份通常不同，不应直接混榜。生成器源码在 prepare 后发生变化时，start/submit/grade 会拒绝继续，应回到原版本或建立新实验，不能把新裁判结果挂到旧比较身份下。

公共目录布局：

```text
README.md
experiment.json
assignments.json
tasks/R1/ ...                      每题共享只读输入
answers/R1-direct-r01/README.md    独立会话入口
answers/R1-direct-r01/work/        Agent 实际工作目录，启动时自行创建
answers/R1-direct-r01/sealed/      submit 成功后一次性生成
```

公共样例采用演示实例；各题各轮真正用于评分的随机 seed 只保存在仓库的 `reports/experiments/<id>/organizer.json`，不写入参赛目录。同一题同一轮的不同提示词使用相同私有 seed，减少样本差异干扰。`reports/` 已被仓库忽略。不要把整个主办方仓库交给需要隐藏题目的外部选手，应只分发公共 workspace；本机目录限制和只读权限不构成恶意代码安全隔离。

## 答案沉淀与封存

让 Agent 打开 workspace 的 README，然后选择 assignments 中的一次尝试。答案可以是策略文件、代码目录或题面规定的前端适配器。保存简短说明、复现命令、实际自测日志和仍然失败的项，不要求私人思维链。

单文件提交：

```bash
python3 scripts/experiment.py submit \
  --workspace workspaces/experiments/extreme-v02-study-001 \
  --attempt R1-direct-r01 \
  --source /absolute/path/policy.py \
  --metrics experiments/metrics.example.json
```

目录提交必须显式声明裁判入口，不能根据猜测选择文件：

```bash
python3 scripts/experiment.py submit \
  --workspace workspaces/experiments/extreme-v02-study-001 \
  --attempt C1-hypothesis-r02 \
  --source /absolute/path/solution-directory \
  --entrypoint .
```

对于含前端适配器、页面和日志的目录，`--entrypoint` 使用题面规定的适配器相对路径，例如 `adapter.py`。先核对该题公开协议，不能把任意 HTML 当成语义适配器。单文件来源的入口即该文件名。

提交仅复制文件，**不执行答案**。目录经检查后原子导入；禁止软链接、特殊文件、路径逃逸、已有答案覆盖；限 10,000 个文件、合计 256 MiB。manifest 保存文件相对路径、字节数、SHA-256、来源和入口；其自身 SHA-256 另保存在主办方私有收据中。因此修改答案及同步修改公开 manifest 仍会被检测。封存是单次操作，重新试验请建立新轮次或新实验。

```bash
python3 scripts/experiment.py inspect \
  --workspace workspaces/experiments/extreme-v02-study-001
```

inspect 报告 `missing/sealed/tampered`，并检查共享题面/数据指纹。缺交会明确列出；损坏时退出码为 2。grade 会拒绝缺交、被改动的答案或被改动的公共题包。

实验控制文件也会冻结：根 README、experiment.json、assignments.json、所有 attempt 的 README，以及存在时的 efficiency-budgets.json。inspect 的 `control_integrity` 分别报告是否已冻结、逐文件检查和整体状态，`generator_integrity` 报告生成器源码是否仍匹配；两者纳入 integrity_ok。修改提示词、任务分配或预算后，start/submit/grade 均拒绝继续。work/ 和 sealed/ 不在控制文件清单中，答题者可以正常编辑自己的工作副本。没有旧控制指纹的历史实验标记为 `not_frozen`，不能默认为正式可评分；需要新建实验，不能回填指纹为已发生的实验补造冻结证明。

## 时间、token 与效率证据

统一字段为 `total_ms / ttft_ms / output_tokens / reasoning_tokens / thinking_time_ms`。无法从当前工具观察到的字段填 null，不得通过字数估算 token，也不得把首字等待时间当成内部思考时间。`source` 允许 `agent_self_reported / host / API`，可附 `evidence_files` 指向答案目录内的日志。

**source 字符串不构成可信证明。** 即使提交声称来源为 host 或 API，导入后仍标记为 `unverified`、`efficiency_eligible=false`。Codex 必须核验独立的宿主计时或 API usage 原始证据、请求/会话标识和计数范围，才能在后续汇总评分中采用它；默认自报数据不用于效率扣分。预算字段是实验声明，模型平台的实际限时/token 限制需要宿主执行；这个提交工具没有伪装成已执行预算限制。

## Codex 独立评分

答案先封存，再让 Codex 阅读 [GRADER_README.md](GRADER_README.md)，显式运行：

```bash
python3 scripts/experiment.py grade \
  --workspace workspaces/experiments/extreme-v02-study-001 \
  --attempt R1-direct-r01
```

grade 将封存答案复制到新的私有评测目录，调用实际 `scripts/extreme.py --submission ...`，保存真实裁判报告、进程证据及指纹，不读取 Agent 自报 pass 作为判定。每次复跑生成独立记录，不覆盖之前的评分。前端自动结果仅为语义分，UI、交互体验、无障碍及独立视觉判断仍记为 pending。

核心流程回归：

```bash
python3 -m unittest discover -s experiments -p 'test_*.py' -v
```

## 自动汇总与效率换算

`prepare`会把预登记efficiency_policy与哈希写入公共experiment.json及私有记录，并提供efficiency-budgets.json。样例默认elapsed_only，不把不可观察的内部思考时间作为预算。

```bash
python3 organizer/aggregate_experiment.py --workspace <workspace> --model <model-id> --output reports/aggregate.json
python3 organizer/leaderboard.py reports/aggregate.json --metric quality --scope automated
```

先对每种提示词的所有预定轮次取median，再对提示词等权平均；缺交/非法为0，待评null。同一封存答案只选最早真正完成的评分。完整UI榜默认不采纳仅semantic-only的前端成绩；`--scope automated`明确只比较已定义的自动检查部分。

时间/token换算与缺失处理见 [EFFICIENCY.md](EFFICIENCY.md)。只有独立证据核验后才算效率；预算必须与prepare时的哈希一致。不能因为模型没报告隐式思考就给它零计算成本。

## 创建可编辑工作副本

共享题包只读。需要时可由主办方执行 `python3 scripts/experiment.py start --workspace <workspace> --attempt <attempt-id>`，只为该尝试生成可编辑的work副本，不启动模型、不声称开始了可信模型计时。已存在工作副本或已封存答案不会被覆盖。
