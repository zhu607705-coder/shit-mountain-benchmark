# 流式时延与 token 采样：可选的宿主证据

**主流程是 Agent 读取[实验 README](../experiments/README.md)、独立做题、保存答案和自测记录、封存提交，再由 Codex 按[评分说明](../experiments/GRADER_README.md)运行裁判。** `performance.py` 是宿主有真实 API 接口时可用的流式采样器，不是主 Agent 启动器，也不会替 Agent 读仓库、调用工具、修改文件或执行测试。

没有 API usage、宿主计时或平台提供的可信指标时，缺项就保持 `null`。提交一份声称来源为 host/API 的 metrics 文件不会自动取得效率评分资格；Codex 仍需核对日志、请求/会话标识、文件指纹与计数范围，确认它覆盖整个答题 attempt。单次文本 API 调用的耗时不能冒充一个包含工具、编辑和自测的完整工程任务耗时。

## 先跑本机模拟演示

以下命令启动临时 loopback HTTP SSE 服务，使用无任何外部访问能力的合成 credential，执行 **3 个 prompt × 3 轮 = 9 次真实本机 HTTP 请求**，然后关闭服务。回答与 usage 都是服务端合成值；只有回环传输与短暂等待的时延是实际测量值。生成物均明确标为 `simulated=true`，不表示任何模型的答题能力、远程服务性能或隐藏思考耗时。

```bash
python3 integrations/test_performance.py
python3 integrations/performance_demo.py \
  --output reports/performance-demo-v02-001 \
  --rounds 3 \
  --seed 260926
```

输出目录必须是新目录，避免混入前一轮样本。示例输入为 [performance-prompts.example.json](performance-prompts.example.json)，分别给出独立的推理、代码原子性和前端快照问题。它们用于检查采样与统计接口；真正比赛题仍以实验工作区 README 和题面为准。

| 文件 | 内容 |
|---|---|
| `attempts.jsonl` | 每次 API attempt 的完整观测、可见回答、prompt 指纹、轮次、重试编号与来源标记 |
| `attempts.csv` | 可直接导入表格的指标；包含 simulated、来源、模型标识与三类首次时刻；未知值为空单元格 |
| `summary.json` | 全部尝试、成功尝试、逻辑运行的统计与分 prompt 汇总；保留缺失数和失败数 |
| `DEMO_README.md` | 仅模拟演示生成，说明合成数据范围与不可据此作出的判断 |

可见回答保存在 JSONL 的 `response_text`。采样器只记录 reasoning 流是否出现、字符数、事件数和公开传输时刻，**不保存 `reasoning_content`/`reasoning` 原文**。输入 prompt 不复制到结果目录，使用其规范化内容 SHA-256 关联原计划。

## 宿主具有真实 API 时

复制并填写 [config.example.json](config.example.json) 的 Base URL、模型标识与密钥环境变量名。密钥值通过宿主环境注入；配置和结果只保留变量名。配置中的 `api.example.com` 与模型字符串是占位符，不是可直接使用的服务。

```bash
python3 integrations/performance.py \
  --config /absolute/path/provider-config.json \
  --prompts integrations/performance-prompts.example.json \
  --output reports/provider-run-001 \
  --rounds 3 \
  --warmups 1 \
  --retries 0 \
  --seed 260926
```

接口为 Chat Completions 兼容 SSE，发送 `stream=true` 与 `stream_options.include_usage=true`。按提供商实际支持情况选择 `--token-limit-field max_completion_tokens` 或默认的 `max_tokens`，必要时显式指定 `--reasoning-effort`。参数必须能被目标接口接受，采样器不把一个提供商的参数语义套到另一个提供商上。

如果接口返回普通 JSON，仍保存可见文本、总耗时与 provider usage，但所有流式首 token 时延保持 null。流未正常结束、HTTP 分块中断、提供商流错误都会作为未完成或失败 attempt 保留，不会只留下成功轮次。默认不重试；需要重试时显式使用 `--retries 1`，最多为 3。

## 指标口径

计时起点是宿主发起请求前的单调时钟，单位均为毫秒。下面几个首次时刻分别记录，不可互换。

| 字段 | 观测定义 | 不应解释为 |
|---|---|---|
| `response_headers_ms` | 宿主取得响应头的时间 | 模型开始生成的时刻 |
| `first_event_ms` | 收到第一个可解析 SSE payload 的时间；可能只有 role | 首个可见答案 token |
| `first_reasoning_delta_ms` | 首次收到提供商公开的 reasoning delta 的时间 | 内部开始思考或思考完成时间 |
| `ttft_ms` | 首次收到非空可见答案 `content` delta 的时间 | 首事件时间、浏览器绘制时间或隐藏思考耗时 |
| `observed_reasoning_stream_span_ms` | 首次至末次 reasoning delta 的观测跨度，至少两条时才有值 | 完整内部推理 wall time |
| `total_ms` | 本次请求至结束/错误的宿主耗时 | 纯生成计算耗时 |
| `thinking_time_ms` | 此传输无法观测，始终 null | TTFT、总时延或 reasoning delta 的跨度 |

这些时刻包含网络、服务排队、缓存、传输和客户端读取等因素。即使提供商发送 reasoning delta，它也没有向客户端暴露模型内部完整的思考开始/结束时刻。流式接口按事件交付内容的示例见 [OpenAI streaming cookbook](https://developers.openai.com/cookbook/examples/how_to_stream_completions)。

Token 使用提供商返回值，不通过中文字符、英文单词或流式 chunk 数猜测：

| 字段 | 口径 |
|---|---|
| `input_tokens` | provider 报告的 prompt/input token；缺失为 null |
| `output_tokens` | provider 报告的总生成 token，可能含 reasoning 与不可见格式内容 |
| `reasoning_tokens` | provider 明确报告的 reasoning token；未给出则 null |
| `non_reasoning_generated_tokens` | 两个计数都有效时的 output−reasoning，仅代表非 reasoning 生成 token |
| `visible_output_tokens` | 本采样器没有独立准确分词证据，保持 null |
| `visible_output_chars` / `visible_output_bytes` | 收到的可见文本字符数与 UTF-8 字节数；不称为 token |
| `provider_output_tokens_per_second` | provider 总生成 token 除以整次请求耗时，是包含等待的均摊指标 |

**`output_tokens − reasoning_tokens` 不等于准确的可见输出 token。** 输出计数可能还包含不可见的消息/格式内容；有关计数范围见 [OpenAI token counting](https://developers.openai.com/api/docs/guides/token-counting)。reasoning token 的可见性、usage 和预算关系见 [OpenAI reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)。这些来源说明 OpenAI 的接口口径；其他兼容提供商的报告范围还需核实。

标准 usage-only 尾块允许 `choices=[]`，采样器仍读取 usage。正常 `[DONE]` 但没有 usage 的响应可记录为完成，token 缺项保持 null；收到 stop 后连接却在 `[DONE]` 前断开，不视作完整流。

## 多轮、重试、连续会话

默认每个 prompt 独立请求；每轮按 `--seed` 确定性打乱顺序，保留每个 prompt 的全部轮次。summary 同时给出 observation/missing、均值、最大值、最小值、P50/P95 与和。P50/P95 按排序样本线性插值，是描述统计，不是置信区间；三轮不支持宣称稳定的尾部性能。

- `all_attempt_metrics` 包含成功和失败请求的已有观测；不能把有缺项的失败记成零成本。
- `successful_attempt_metrics` 只描述成功请求，同时保留全部失败数，不能单独拿它宣称总体成功率或完整成本。
- `logical_runs` 表示一个 prompt 的一个轮次，允许包含多次 retry；不会把多次请求当成多道独立题。
- `logical_total_ms` 累计该逻辑运行从首次请求至最终成功/放弃的墙钟时间，含之前失败和记录开销。
- `logical_ttft_ms` 是整个逻辑运行首次看到非空可见片段的时刻，片段可能来自失败尝试，不能称为最终完整答案的等待时间。
- `logical_output_tokens` / `logical_reasoning_tokens` 只有该逻辑运行的每次 attempt 都给出相应 usage 才能求和；任何一次缺失就为 null。`output_tokens_known_lower_bound` 仅是已知 usage 的和，不是完整费用。
- warmup 的原始记录保留，`warmup=true` 的请求从正式统计中排除，排除数量单列。不挑最好一轮，也不把最小值改名为正常耗时。

`--conversation` 按计划顺序保留成功问答，下一轮从空历史重新开始，不继承 warmup。它测试上下文增长下的连续会话，不能与独立 prompt 的输入成本直接混合。某一 turn 重试后仍失败时，本轮后续 turn 停止执行；summary 的 `not_executed_logical_runs` 明示未执行数量，不会悄悄跳过失败上下文继续对话。

## 交给 Codex 核验

采样记录只是实验的证据之一。将属于同一答题 attempt 的完整宿主记录、代码/答案、自测日志和来源关系一并封存，再按实验 README 提交。Codex 应先核对请求范围、轮次、重试、usage 缺失和 simulated，再运行实际题目裁判。质量得分与速度/token 指标分别保留；只有同题同轮、预算可比且证据已核验时，才可按冻结的赛制进行效率比较。

本机模拟结果永远不能替代真实提供商测量。即使某个实际请求非常快，也不能据此判断它完成了仓库定位、修改、自测或整体功能验收。
