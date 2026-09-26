# 时间、输出与过度计算的计分口径

主流程是 **Agent 读取实验 README → 运行独立尝试 → 统一沉淀答案与证据 → Codex 独立评分**。采样器只是宿主的一种记录工具，不要求所有参赛者通过同一家模型 API。

## 每次保存什么

| 字段 | 含义 | 缺失时 |
|---|---|---|
| `output_tokens` | 服务/宿主报告的生成 token 总数 | null，不按字数猜 |
| `reasoning_tokens` | 服务明确报告的推理 token | null，不当成0 |
| `visible_output_chars` | 实际可见文本长度 | 可由采样器准确数出，但不是token |
| `total_ms` | 明确边界内的宿主单调时钟耗时 | null，注明测量范围 |
| `ttft_ms` | 请求开始至首个非空可见答案片段 | 非流式/无答案时null |
| `first_event_ms` | 首个协议事件，可能只有role等元数据 | 不充当首字时间 |
| `first_reasoning_delta_ms` | 兼容服务若暴露推理流，首个推理片段到达时间 | null |
| `thinking_time_ms` | 内部思考时间 | 本采样器不可直接观察，始终null |
| `logical_*` | 重试链累计耗时、首字、token | 任一用量缺失时累计token保持null |

API总生成token可能含推理和不可见格式token，因此总数减去reasoning也不能直接称为精确可见token。模型可能在可见输出之间继续推理，首字前等待不能等同于完整内部思考时间。[OpenAI token口径](https://developers.openai.com/api/docs/guides/token-counting)、[推理用量说明](https://developers.openai.com/api/docs/guides/reasoning)。

整个工程答题耗时与一次API请求耗时不同。Codex核验时必须检查是否覆盖全部调用、子Agent、重试和工具操作；不能只用最终一次回复的时间代表整个attempt。裁判自己的运行时间单列为测试成本，也不是模型思考时间。

## 多提示词、多轮统计

实验先冻结题目、提示词变体、轮数、输入与预算。每次使用独立会话，不挑最好的一轮。汇总保留全部预登记尝试：缺交/损坏/真实非法结果为0；封存但未判为null。每个提示词内取各轮median，再对提示词变体等权macro mean。

性能记录提供全尝试与成功尝试两套统计，并保留失败数、缺失数、均值、最大值、最小值、P50、P95。重试的所有消耗都保留，warmup单列；连续会话若一轮中途失败，停止该轮后续问题并记录未执行数量。小样本P95只是描述性统计，不是稳定尾延迟估计。

## 怎么扣“雷霆大思考”的成本

先由独立裁判得到质量 Q，严重正确性失败直接0。然后使用提前冻结的预算，计算效率折扣；预算以内不奖励额外快，也不因为少输出几个字给奖金。

时间效率 `E_t = min(1, 时间预算/实际时间)`。启用首字模式时，再取与`首字预算/TTFT`的较小值。

token效率 `E_n = min(1, 总生成token预算/实际总生成token)`。启用 reasoning-aware 时，再取与`reasoning预算/实际reasoning tokens`的较小值。**总生成token与reasoning不相加**，避免把同一批token重复收费。

默认质量效率分：

`Q_eff = Q × [1 − 0.30 × (1 − E)]`

其中纯时间模式 `E=E_t`；token模式 `E=0.60×E_t+0.40×E_n`。默认最多扣掉Q的30%，权重和上限可以调整，但必须在看答案前冻结。最后在同题、同任务版本、同效率策略和预算中再按最佳有效结果归一化为100。

这惩罚的是超预算的可观察消耗，不是主观判断“它是不是想得太多”。额外计算若提高质量，仍能通过Q体现收益；快而错误的提交不会被效率救活。

## 四种明确分开的测量模式

- `elapsed_only`：只使用独立核验的整体耗时，默认适合README驱动的工程实验。
- `time_only`：整体耗时与TTFT都必须可用。
- `time_tokens`：再要求总生成token。
- `reasoning_aware`：再要求真实reasoning token计数。

缺少所需字段时结果为pending；不能把没有报告reasoning的模型当成零思考。不同模式/预算不可混榜。`thinking_time_ms`不参与公式。

## Codex怎样使用

先读取封存答案与实际宿主/API原始记录，记录所核验文件、指纹、来源和范围。仅有`source:API`或`source:host`声明仍不可信；模拟数据一律不能产生正式效率分。

```bash
python3 organizer/efficiency.py \
  --quality <private-grade>/quality.json \
  --telemetry <verified-complete-host-record.json> \
  --budgets <workspace>/efficiency-budgets.json \
  --profile elapsed_only --verified-host-evidence \
  --output <private-grade>/efficiency.json

python3 organizer/aggregate_experiment.py \
  --workspace <workspace> --model <model-id> \
  --output reports/aggregate.json
```

prepare会把`efficiency_policy`和其哈希同时登记在公共实验配置与私有记录中。汇总拒绝事后更换预算；选择当前封存答案最早真正完成的评分，不能用后面的高分覆盖初次失败。前端自动质量范围为semantic-only，完整UI/视觉分另评。

## 可选流式采样

`integrations/performance.py` 可以产生`attempts.jsonl`、逐次`attempts.csv`、`summary.json`、汇总`summary.csv`。请求最终usage通常在单独尾块到达，断流可能导致用量未知；缺数据不能补0。[官方流式usage示例](https://developers.openai.com/cookbook/examples/how_to_stream_completions)。

`integrations/performance_demo.py`的3提示词×3轮是本机SSE模拟器，用于验证记录链路；其中的token、回复和短等待均为合成数据，不是商业模型性能结果。
