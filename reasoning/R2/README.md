# R2：有副作用的主动诊断策略树

18 项实验、11 种干预、180 个公开潜在世界组成一个原创合成工业系统。树必须处理相关矛盾信号、前置实验、互斥采样、路径预算、延迟及罕见大损失。完整规则见 [PROMPT.md](PROMPT.md)。Python 3.9+，仅标准库，无需联网。

## 实际基线

| 指标 | 本包自适应策略基线 | 最佳固定干预对照 |
|---|---:|---:|
| valid / feasible | true / true | true / true |
| raw_score | **528.051477475** | 319.650920899 |
| 优化目标 objective（越低越好） | 31.281416667 | 74.494444444 |
| 平均总损失 | 12.791 | 50.194444444 |
| 最坏 10% CVaR 损失 | 32.575 | 54 |
| 平均干预损失 | 4.956666667 | 50.194444444 |
| 平均实验副作用 | 2.9295 | 0 |
| 平均延迟损失 | 4.904833333 | 0 |
| 平均实验费用 | 12.772222222 | 0 |
| 平均实验次数 | 4.344444444 | 0 |
| 树节点数 / 最大实验深度 | 121 / 5 | 1 / 0 |
| 最大路径费用 | 18 / 24 | 0 / 24 |

实际文件为 `baseline_output.json`、`baseline_result.json` 与 `control_output.json`、`control_result.json`。对照枚举了 11 种不做实验的固定干预，最优者为 `A10`（停机隔离）。基线分数显著高于这个简单对照，但这不等于最优、真实部署结果或隐藏测试表现。

`baseline.py` 在多种局部风险系数和深度上构造贪心策略树，以公开世界的实际总体得分选择一棵。局部启发式比较“立即终止”与“做一次实验、分支后终止”，随后递归；它没有完整的多步前瞻，也没有全局树搜索。条件 CVaR 的加权和并不等于总体 CVaR，因此最终由裁判整体回放再挑选候选。空样本分支保守返回 `A10`。

## 复现

在本目录执行：

```bash
python3 baseline.py --input input.json --output baseline_output.json
python3 judge.py --input input.json --submission baseline_output.json > baseline_result.json
python3 judge.py --input input.json --submission control_output.json > control_result.json
python3 selftest.py
```

8 项自测实际通过，覆盖精确分数、尾部边界/延迟、漏分支/非法动作/额外字段、重复实验、即使未被公开世界访问也必须验证的分支、前置与互斥、重复 JSON 键与非有限数、公开基线完整回放。

当前公开数据可重新生成：

```bash
python3 generate.py --design-seed 2201 --world-seed 9101 --worlds 180 --output input.json
```

## 新实例与信息边界

本版将**所有世界表完整交给求解器**。所以它测的是有限场景下的策略优化与成本敏感推理能力，不是对未知真值的分类泛化。构造树可以使用全表；执行树只能按所选实验的已得结果走分支。准确率不进入评分。

正式轮次应封存尚未公开的 `design-seed`、`world-seed`、输入哈希、裁判哈希；轮次开始时给各求解器完整新输入，再生成树并评分。下面是公开演示配置，不是隐藏种子：

```bash
python3 generate.py --design-seed 3201 --world-seed 19101 --worlds 360 --output round2_input.json
python3 baseline.py --input round2_input.json --output round2_baseline.json
python3 judge.py --input round2_input.json --submission round2_baseline.json
```

改变 `world-seed` 会重新抽取合成世界，改变 `design-seed` 还会改变部分实验签名。完成后公开封存信息便于复核。不能把旧树直接盲投新的世界、再宣称这是本版已经约定的隐藏泛化评估；若另建训练/隐藏抽样赛道，必须事先约定世界生成分布、公开训练信息、隐藏评分规模及提交冻结机制。

已知简化：测试结果不受顺序干扰，损失可加，潜在世界静态，未知类别和分布漂移没有纳入当前评分。多步实验价值、连续结果、动态系统或真实证据文本可在之后另设实例，不能用当前分数替代这些能力。
