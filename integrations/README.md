# 模型接口与已有提交导入

主流程见 ../experiments/README.md：Agent读取实验README独立答题，答案封存后由Codex评分。本CLI是辅助接口。v0.2默认导出extreme任务；所有12题使用各自公开策略/仓库/语义协议。旧R1/R2单次API决策接口保留为v0.1 legacy兼容功能，不代表新版极难任务的完整Agent执行。

## API 配置

复制 `config.example.json`，将 `base_url`、`model`、`alias` 改为自己的接口。`base_url` 应包含供应商要求的版本前缀，例如 `https://provider.example/v1`，程序会追加 `/chat/completions`。

```sh
python3 integrations/cli.py import-config --source integrations/config.example.json --output .local/model.json
python3 integrations/cli.py inspect --config .local/model.json
```

配置只接受 `alias/base_url/model/api_key_env` 和可选 `timeout/max_tokens/temperature`。**不要把密钥填进 JSON。** 将密钥放在 `api_key_env` 指定的环境变量中，再运行命令；例如通过终端的安全输入或自己的密钥管理器注入 `BENCHMARK_API_KEY`。`inspect` 只报告变量是否存在，不显示值，也不联网。

真实调用是显式命令，无密钥时直接失败，不创建网络连接：

```sh
python3 integrations/cli.py run-reasoning --task R1 --config .local/model.json
python3 integrations/cli.py run-reasoning --task R2 --config .local/model.json
```

默认保存到 `submissions/<alias>/<task>/submission.json`，同目录保存来源元数据和本地裁判的归一化 `result.json`。同名结果不会被覆盖，重复运行请使用新的 alias。会发送完整 `PROMPT.md` 与完整 `input.json`，输入可能较大；模型或供应商上下文不足会明确失败。单次请求、无自动重试、无 streaming、无工具调用。仅支持 Chat Completions 的文本 `choices[0].message.content`，输出必须是完整 JSON 对象或单一完整 JSON 代码块；拒绝前后解释、重复键、NaN、截断和工具调用。

API 密钥仅放在 Authorization；禁止带凭证 URL、禁止 HTTP 重定向、远程接口要求 HTTPS，本地 mock 可使用 HTTP。HTTP 错误正文不会打印。供应商响应若回显密钥，拒绝保存。调用本地裁判时移除当前 API 密钥环境变量；不记录原始响应。来源记录保留接口地址和模型名，公开结果前自行决定是否公开这些身份信息。

## 代码/前端工作区导入导出

```sh
python3 integrations/cli.py export-task --task C1 --output workspaces/C1
python3 integrations/cli.py export-task --task C2 --output workspaces/C2.zip
python3 integrations/cli.py export-task --task F1 --output workspaces/F1
python3 integrations/cli.py import-submission --task C1 --alias external-agent-v1 --source workspaces/C1
python3 integrations/cli.py import-submission --task F1 --alias external-agent-v1 --source /path/to/completed.zip
```

默认extreme导出由各赛道生成，包含当前PROMPT、协议、输入/生成材料及故障起点，具体入口以包内README为准。`--profile legacy` 才使用以下旧布局：C1/C2包含题面、事故记录、核心契约、无期待输出的公开fixture和完整 `repository/buggy/`。C3/C4 导出题面和 `starter/`；F1–F4 导出公开题面和故障页面，F1/F2 另含固定数据；R3/R4 导出策略接口与公开模型/观测。R1/R2 也可单独导出题面与 input。所有导出均排除参考解、oracle、judge 内部和期望结果，并附 EXPORT_README.md 区分本地起步命令与主办方验收命令。

导入**只复制文件并记录 SHA-256、来源名称与时间，不执行提交中的脚本**。目录/ZIP 成员拒绝绝对路径、`..`、反斜线、符号链接、设备文件、重复 ZIP 成员及加密 ZIP；限制 2,000 文件、单文件 16 MiB、总计 64 MiB，并拒绝异常压缩比。目标不允许符号链接、不允许覆盖已存在的提交，校验后先写临时目录再重命名。导入代码仍是不可信代码，路径检查不等于执行隔离。

复杂仓库任务需要外部 agent 的读文件、编辑、运行和反馈循环。此 CLI **不会把一次聊天调用包装成代码/前端已完成**，也不接受会在宿主执行的任意 shell 字符串。对接自己的 agent 时，以导出的独立工作区作为输入；在自己配置的容器/虚拟机里运行工具循环，输出目录后再显式 `import-submission`。真实 Docker 沙箱与外部 agent 进程协议尚未实现。

已有裁判 JSON 可统一成 `task_id/model/alias/valid/raw_score/machine_score/human_visual_score/metrics/source_result`：

```sh
python3 integrations/cli.py normalize-result --task C1 --alias external-agent-v1 --source existing-result.json --output normalized-result.json
```

这只是字段归一化，不重新判分，不会把用户自报分数当作已验证比赛结果。代码/前端导入后需继续由主办方在隔离环境运行正式评测；前端人工盲评分未知时保留 `null`。

## 本次验证边界

```sh
python3 -m unittest discover -s integrations -p 'test_*.py' -v
```

测试使用本机 loopback mock HTTP，覆盖无密钥不调用、Authorization格式、完整R2题面/input发送、严格JSON解析、实际本地judge衔接、密钥不落产物、凭证回显拒绝、路径穿越/符号链接/压缩炸弹拒绝、惰性导入和解题数据不导出。它不使用真实 API key，不联系真实模型供应商。真实供应商兼容性、R1模型质量、完整外部agent工具循环及Docker执行隔离未验证。

## 性能记录与多轮统计

见 [PERFORMANCE.md](PERFORMANCE.md)。流式记录器是可选宿主工具；主流程不强制API。内部思考耗时未观测时保持null，总输出token不等于可见字数。质量/效率扣分见 ../experiments/EFFICIENCY.md，封存来源标签不会自动取得信任。
