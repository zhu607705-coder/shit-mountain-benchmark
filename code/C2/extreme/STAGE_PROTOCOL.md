# C2 stage-v2：取消恢复槽与不可变图版本相互污染

提交目录必须有 `extreme.py` 导出以下接口；它与旧 HTTP/worker 仓库共同构成 extreme 资格。旧代码缺少接口会单列 capability_gap，不作为难度证据。导出包含真实可运行、持久 SQLite 的故障 starter，不能只提交空协议。

```python
class BuildService:
    def __init__(self, root): ...
    def set_graph(self, project, graph) -> int: ...
    def enqueue(self, project) -> str: ...
    def cancel(self, job_id): ...
    def run(self, job_id, hook=None) -> dict: ...
    def get(self, job_id) -> dict: ...
```

graph 是 `{'inputs': [整数,...], 'factor': 整数}` 的最小图协议，值为 `sum(inputs)*factor`；这个小代数核用于集中暴露生命周期错误，并不代替原5000节点DAG任务。每项目 revision 从0开始，每次 set_graph 增加1；enqueue 原子固定当前图与revision，返回唯一任务ID。run/get返回 `{'status': 'pending'|'running'|'cancelled'|'done', 'value': int|None, 'revision': int}`。已取消任务不得再成功，done和cancelled是终态；新任务与旧任务取消状态分离，重开保留图、任务、结果。

`run` 若有 hook，在已经得到且持久保存可恢复中间结果、发布成功之前调用一次 `hook('after_prepare')`。hook 可通过另一个 service handle 取消任务；run 必须重新检查取消并返回cancelled/None。允许丢弃中间结果重算，也允许保留正确版本的纯结果，不能跳过hook。

三个真实轨迹：取消后在同图重试；正常成功后更换图；取消旧图→更换图→重开worker→新任务重试。starter前两项通过，组合项复用了按project保存、没有图revision的恢复槽，发布了旧值。微型可行证据：旧图(2+3)×2=10，新图(9+16)×3=75，取消旧任务后新任务必须75。

每个成功结果必须归属于其不可变图身份。full有12组不同图值组合；不限制具体缓存/恢复表布局。整个提交还需通过原HTTP服务、隔离、迁移和深DAG回归。当前gate不把代码长度或架构选择作为分数。
