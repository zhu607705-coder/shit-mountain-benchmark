# C4 stage-v2：构建期间 manifest 可以变化，产物必须来自同一个 cut

本节明确扩大旧题条件：**只对新stage-v2接口，构建期间允许另一handle更新manifest**。旧Builder(root,cache).build接口仍沿用“单次build源不变”，不追溯修改旧合约。提交目录extreme.py必须导出VersionedBuilder；缺失接口为capability_gap且不具备extreme资格。

```python
class VersionedBuilder:
    def __init__(self, root): ...
    def update(self, sources: dict[str,str], env: dict[str,str]) -> str: ...
    def activate(self, version: str): ...
    def build(self, hook=None) -> dict: ...
# 可选：class RetryRequired(RuntimeError): ...
```

update把源文本与环境绑定原子地发布为一个不可变manifest，返回不冲突的version；旧version可再次activate。源文本按源名字排序以 `|` 拼接，后面加 `#`，再将env值按键排序以 `|` 拼接。build返回 `{'version':version,'data':text}`。version与产物必须属于同一完整manifest；若无法得到一致cut，可以在缓存污染前显式抛RetryRequired，裁判会对当前manifest重试。

首次未命中的build若有hook，完成该次源内容采集后、环境/产物发布前必须调用一次 `hook('after_sources')`；hook会经另一handle原子更新sources与env。实现可以提前固定整个manifest，然后在hook后继续用旧完整版本，或检测到变化后重试新完整版本。不能返回旧源+新环境，也不能把混合产物发布到旧version的共享缓存。缓存命中不要求重复hook；裁判使用未构建的新version保证注入确实发生。

局部控制：不变化的build；更新完成之后再build。组合：采集旧sources→hook发布新sources/env→完成构建→重开handle→activate旧version→再build。故障starter的源绑定来自旧manifest，环境却被刷新为新manifest；两个局部控制通过，组合真实失败，且混合产物被缓存污染。裁判校验实际manifest/源文件与产物返回值，不依赖候选stats。

tiny witness允许 `old-a|old-b#old` 或 `new-a|new-b#new` 配对相应version，禁止 `old-a|old-b#new`。full有12条数据不同的组合轨迹，另保留20root/1000变更/12进程缓存压力。新机制需要同时考虑一致性采集、manifest身份、显式重试和原子缓存发布；修旧递归栈并不能通过这项资格。
