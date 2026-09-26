# C1 stage-v2：逻辑转账跨物理分片代际的幂等性

本接口是 extreme 的**必需资格门槛**。把修复后的扩展放在提交目录的 `extreme.py`，并同时保留原服务仓库接口。导出包已经放入一份可以直接运行的故障 starter。旧基线没有本接口时为 `capability_gap`，不能算作旧算法运行失败，也不具备 extreme 资格。

```python
class Ledger:
    def __init__(self, root): ...  # Path/string; reopened handles share durable state
    def open_account(self, name: str, balance: int): ...
    def migrate(self, name: str) -> int: ...  # returns next physical epoch
    def transfer(self, txid: str, source: str, target: str, amount: int,
                 hook=None) -> dict: ...
    def snapshot(self) -> dict[str, int]: ...
```

`open_account` 输入为不同名字与非负整数。迁移保留逻辑账户身份、余额和所有影响将来重试的历史，可改变物理表、分片或文件。测试只在已知账户上操作。转账原子地从 source 扣款、给 target 加款，余额不足或同一逻辑 `(source,txid)` 的不同载荷应抛 ValueError/RuntimeError。相同逻辑请求无论经过多少次迁移、重开都只生效一次，返回相同 `{'txid': txid, 'amount': amount}`。金额为正整数，不涉及汇率。

若提供 hook，首次成功转账的余额与 receipt 已经原子提交之后、向调用者返回前，必须调用 `hook('after_commit')`。该 hook 可抛异常模拟响应丢失，异常不能撤销已经承诺提交的交易。重复请求不再次调用 hook。hook 是明确的故障边界，不允许忽略。

公开三个对照轨迹：单独丢 ACK 后重试；单独迁移后转账；丢 ACK→两端迁移→重新打开→原请求重试→不同载荷冲突。故障 starter 的前两条真实通过，第三条会重复扣款，因为 receipt 被错误地按 source 的**物理 epoch**分区。裁判检查实际 SQLite 结果，而非检查代码文字。tiny witness 为 a=100/b=0 转账10，迁移并重试后必须仍90/10。

full 用12个不同 seed 派生的余额/金额/迁移次数运行组合轨迹；这部分不是12倍推理难度证明。候选必须同时通过局部控制和组合轨迹，并完成旧 HTTP/worker 全功能回归。修复结构完全开放：逻辑 receipt、迁移 lineage、全局协调表等均可。正式成绩还需性能与自测质量标定，当前只给真实正确性门槛。
