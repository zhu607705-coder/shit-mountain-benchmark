# 作者基线实测报告

所有结果来自实际本机执行，Python 3.14.4，macOS-27.2-arm64-arm-64bit-Mach-O。测试使用真实HTTP、SQLite文件和独立worker进程，不以函数mock替代。完整逐项数据在C1目录repository_buggy_result.json与repository_baseline_result.json。

```sh
python3 -B e2e_env_judge.py --submission repository/buggy --output repository_buggy_result.json
python3 -B e2e_env_judge.py --submission repository/baseline --output repository_baseline_result.json
```

| 环境场景 | 修复前 | 修复后 |
|---|---|---|
| default_flow | 通过 | 通过 |
| legacy_schema | 失败 | 通过 |
| unicode_workdir | 失败 | 通过 |
| interrupted_worker | 失败 | 通过 |
| duplicates_reordering | 失败 | 通过 |
| concurrent_isolation | 失败 | 通过 |
| restart_persistence | 通过 | 通过 |

修复前：环境2/7、核心10/63、自测0/10，诊断原分23.174603，valid=false，裁判耗时5.138秒。
修复后：环境7/7、核心63/63、自测10/10，原分100.0，valid=true，裁判耗时2.068秒。

自测在repository/baseline内实际执行 `python3 -B -m unittest -v test_submission.py`：5个测试全部通过（该次0.014秒）。正向对照通过后，5个新进程/临时副本上的公开行为变异全部被检测，各自出现1个断言失败、0个测试错误。原starter只有1个smoke测试，正向通过但5个变异全部存活，故得0分；没有把测试用例数量等同于质量。

迁移重放回归曾实际先失败：`python3 -B -m unittest -v test_submission.RepositoryTests.test_legacy_migration_preserves_history_and_identity` 得到 `ServiceError: REQUEST_CONFLICT`。对迁移载荷做规范化后，相同测试及完整套件转绿。新增覆盖包括旧请求重放、旧记录保留和升级后跨租户同request_id，避免只补claimed_at列而保留旧唯一约束。

核对说明：核心回归的--submission指向同一repository/baseline，worker导入其engine.py。结果记录suite_sha256、submission_sha256、环境和UTC测量时间。端到端裁判每项finally终止并wait其启动的进程，临时数据库和仓库由TemporaryDirectory清理。

当前100分表示这套有限公开矩阵和5种公开变异已覆盖；不表示未知缺陷检测率100%、隐藏集成绩或最优架构。未验证生产认证、跨主机分区、磁盘损坏、不可信提交安全隔离及无限数据吞吐。
