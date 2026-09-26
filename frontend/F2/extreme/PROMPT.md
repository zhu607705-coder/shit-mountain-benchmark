# F2 · 合并以后才出现的非法排程

本文件是统一 F2 题的 extreme 执行档。旧 starter 仍是修复起点，编号、目标与开放布局保持统一。full 输入规模：**1,200 个任务（旧题12的100倍）、20个回放副本、117,600 次因果事件递送**。smoke 缩小记录数但保留相同耦合机制；不能把 smoke 通过当作 full 完成。

两个离线编辑各自满足排程约束，合并后同时破坏资源占用和前置依赖。用户在冲突尚未解决时继续改字段；远端给出观察了全部候选的解决方案，本地随后撤销旧操作。另一个窗口在存储失败后迁移旧schema并恢复。

## 必须完成的推理和工程工作

1. 区分字段竞争、全局排程约束、未落盘和历史回放四类问题，分别解释可执行修复。
2. 恢复因果历史时要允许网络反序；不同来源的低counter也可能因果晚于高counter。
3. 提供局部修复建议，但必须保留全部原意图且由用户明确接受；撤销不能抢回远端已解决的字段。

所有自动验收语义见 [PROTOCOL.md](PROTOCOL.md)，没有未公开的业务规则。你可以选择数据结构、存储方式、冲突交互和界面布局，结果按可复验质量比较。允许提交明确的残余缺陷和部分完成结果；基线只是一个可运行下界，不代表题目已解。

## 开始运行

导出包内有压缩公开 trace 和解压脚本。压缩只是降低分发体积，full 执行仍会展开并处理全部记录。

```bash
python3 generate_fixture.py --output trace.jsonl
python3 starter_adapter.py < trace.jsonl > responses.jsonl
python3 -m http.server 8765
```

打开 `http://localhost:8765/starter.html` 查看旧系统，打开 `http://localhost:8765/trace-viewer.html` 检查轨迹分布。网页查看器只是输入检查工具，不能证明参赛 UI 通过。starter_adapter.py 是新写的弱语义适配器，运行了有限版本/字段策略，**不是旧HTML本体测试，也不是全功能答案**。

在主仓库验收：

```bash
python3 frontend/extreme.py --task F2 --scale smoke --submission /absolute/path/adapter.py --output result.json
python3 frontend/extreme.py --task F2 --scale full --submission /absolute/path/adapter.py --output result-full.json
```

## 交付与整体可用性

- 完整可启动网页、源码、依赖锁定与一步启动脚本；`adapter.py`/`adapter.cjs` 必须与网页调用同一状态引擎，附路径映射。
- 修复前的最小复现、定位报告、补丁、自测和复验日志；至少包含一个跨机制故障以及其余核心流程回归。
- 真实浏览器操作回放：多窗口、刷新恢复、后台更新中的输入/焦点、键盘替代拖拽、中文输入法、320/390/768/1440px布局。
- 全量数据的导入、下载文件重建、长时负载与资源指标；未运行的项目标为 pending。
- result.json 中语义分、性能、可访问性、人工视觉分分别报告；未经独立测量的质量分为 null。

## 测量边界与难度

自动 trace runner 独立校验公开状态与全量导出内容，可定位因果、身份、约束与恢复错误；它不执行任意HTML，不负责替代原生存储/下载或人工视觉盲评。完整赛事还需要原生UI验收，并核查适配器和页面属于同一实现。

增加规模和机制不等于已证明“比所有模型难10倍”。本档的可证事实是输入规模、非交换操作、约束耦合与弱基线失败；尚无跨模型耗时/成功率难度标定，不保证任何模型必败。没有预设唯一视觉方案或最优工程算法。公开seed用于开发；正式轮由组织者在提交前冻结新的扰动seed、事件交错和预算。
