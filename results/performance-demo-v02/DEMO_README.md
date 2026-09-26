# 本机模拟演示

所有数据均 simulated=true。仅用于验收流式采样接口和多轮统计。
这里的回答与provider usage是本机HTTP服务合成值；实际测量的是本机回环与短sleep的时延。
不是模型能力、真实服务延迟或隐藏思考耗时。每个prompt保留全部轮次，不挑最好一次。
attempts.jsonl保留可见回答，attempts.csv用于表格比较，summary.json有均值/最大值/P50/P95。
真正解题需按实验README由Agent自行执行并提交源码/答案，再由Codex裁判按公开契约评分。
