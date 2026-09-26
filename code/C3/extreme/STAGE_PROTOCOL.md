# C3 stage-v2：旧 writer 的压缩发布不能抹掉新 writer 的 ACK

这是在原Store API之外新增的必需代际协议，提交目录的 `extreme.py` 导出它。旧baseline缺失接口只能报capability_gap。导出中的故障starter使用真实JSON文件、fsync与原子replace，局部功能正常但组合后丢数据。

```python
class GenerationStore:
    def __init__(self, root): ...
    def commit(self, txid: str, updates: dict[str, str|None]) -> int: ...
    def snapshot(self) -> dict[str, str]: ...
    def prepare_compaction(self): ...  # opaque token, captures a version/epoch
    def migrate_writer(self) -> int: ...
    def publish_compaction(self, token) -> bool: ...
```

updates 的 None 为删除；同txid同载荷幂等返回原版本，不同载荷报ValueError/RuntimeError。snapshot是不可变逻辑快照，后续操作不能改变调用者已拿到的映射。新实例打开同root读取同一持久状态。migrate_writer原子切换writer epoch并保留状态、版本和事务receipt。测试在单进程多个handle之间精确排列操作，因此不强求特定OS锁API。

prepare_compaction捕获一个完整状态与代际的opaque token。发布可以重试，旧token遇到更新的版本/epoch时可以返回False或抛RuntimeError，但**不得覆盖任何新ACK，不得复活已删除键，不得回退receipt**。返回True也必须保留全部承诺状态。实现可以拒绝、重做压缩或合并，不规定token格式。

局部控制一是prepare→publish，没有代际变化；控制二是迁移→新writer写入，没有旧压缩发布。组合轨迹为提交a并拿旧快照→准备旧压缩→迁移writer→新handle提交b并删除旧键→旧handle迟到发布→重开并重放a/b。starter将旧token提升为当前epoch再replace，前两项通过，组合项丢b且删除复活。这个失败与递归深度或大数据无关。

tiny witness：旧快照 `{a:1, deleted:3}`；新ACK为 `{a:1,b:2}`；旧publish被拒绝后仍 `{a:1,b:2}`，旧快照保持原样。full使用12组不同数据的同类交错，此外仍有原6切点×4故障×12持久历史和10万键压力。正确性门槛全部通过后才讨论吞吐/空间/恢复时间。
