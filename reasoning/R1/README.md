# R1：相关扰动下的鲁棒调度

这是一个公开、固定的原创合成优化实例。48 个任务、3 个模式、3 类资源、3 个作业区、4 个地区和 24 个情景共同决定评分。完整规则见 [PROMPT.md](PROMPT.md)。需要 Python 3.9+，仅使用标准库，无需联网。

## 实际基线

| 指标 | 本包启发式基线 | 简单对照：只做必选根任务 |
|---|---:|---:|
| valid / feasible | true / true | true / true |
| raw_score | **212.870434383** | 92.357480971 |
| 平均覆盖率 | 0.302334143 | 0.110060880 |
| 最差 20% 情景覆盖率 | 0.204009516 | 0.100612217 |
| 平均最差地区覆盖率 | 0.225699162 | 0.088910270 |
| 成本 / 预算 | 446 / 450 | 100 / 450 |
| 选中任务数 | 38 / 48 | 8 / 48 |

数值来自本目录实际运行保存的 `baseline_result.json`、`control_result.json`。这不是最优解证明、模型间排行榜或隐藏测试结果；原始分也不是赛会归一化分。

`baseline.py` 使用固定随机种子做 96 次预算内拓扑贪心构造，混合模式选择、价值密度和地区均衡启发式，再用全部公开情景挑选候选。它没有搜索全部选择组合，没有局部换序修复，也没有求出最优性界。跨链选择、预算分配、模式与顺序联合搜索仍有改进空间。

`valid` 与 `feasible` 表示提交格式、选择闭包和预算合法；必选任务必须入计划，但情景中仍可能无法排程，此时收益为 0。逐任务记录可检查实际完成情况。

## 复现

在本目录执行：

```bash
python3 baseline.py --input input.json --output baseline_output.json
python3 judge.py --input input.json --submission baseline_output.json > baseline_result.json
python3 judge.py --input input.json --submission control_output.json > control_result.json
python3 selftest.py
```

7 项自测实际通过，覆盖已知精确分数、资源中断与无法排程、互斥/容量逐时刻复核、非法 ID/缺项/重复任务/预算/依赖、分数尾部边界、重复 JSON 键与非有限数。

当前公开数据的可再生命令：

```bash
python3 generate.py --instance-seed 1601 --scenario-seed 9001 --scenarios 24 --output input.json
```

## 新实例与封存 seed

举办正式轮次时，组织者先独立选定尚未公开的 `instance-seed`、`scenario-seed` 和情景数，将种子配置、输入文件哈希、裁判版本哈希写入封存记录。下列数字仅为新的**公开示例**，不能当作秘密种子：

```bash
python3 generate.py --instance-seed 2601 --scenario-seed 19001 --scenarios 48 --output round2_input.json
python3 baseline.py --input round2_input.json --output round2_baseline.json
python3 judge.py --input round2_input.json --submission round2_baseline.json
```

本版契约是在轮次开始时把完整新 `input.json` 发给每个参赛求解器，各自生成新计划，然后按相同输入评分；结束后公布封存记录供复核。只改变情景 seed 会保留任务和模式但改变扰动集合；改变实例 seed 也会改变任务参数。不要把旧计划直接对新输入的分数包装成模型处理新题的能力。

这里没有实现远端隔离、运行时限、模型费用统计或防作弊平台，这些属于赛会编排层。当前数据规模是可运行首版；提高任务数量或改变拓扑需要扩展生成器并重新验证，而不是宣称已经覆盖真实调度难度。
