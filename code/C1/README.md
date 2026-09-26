# C1：真实仓库故障修复题 v0.2

主任务已升级为HTTP + SQLite + 独立worker的仓库级故障修复。先读PROMPT.md和repository/INCIDENT.md，完整starter在repository/buggy/，我方修复在repository/baseline/。

```sh
python3 -B e2e_env_judge.py --submission repository/buggy --output repository_buggy_result.json
python3 -B e2e_env_judge.py --submission repository/baseline --output repository_baseline_result.json
python3 -B judge.py --submission repository/baseline
python3 -B selftest_mutation_judge.py --submission repository/baseline
```

无需第三方依赖。端到端裁判自动建立临时仓库/DB，选择动态端口、真实启动服务和worker，验证7项矩阵，回收进程与临时文件。评分为环境70、同仓库核心回归20、自家测试变异检测10；保存的repository_*_result.json是实测结果。

我方诊断与验证证据在repository/baseline/DIAGNOSIS.md、TEST_REPORT.md、test_submission.py。自测由基线作者新增，主办方再做正向对照与5项公开变异检查，并未把主办方测试冒称为候选者自测。

旧buggy/、baseline/与旧结果保留为v0.1核心参考，业务合约在CORE_CONTRACT.md。主提交worker与judge.py --submission repository/...运行同一份engine，不能用独立参考代码替换仓库实际调用代码来得分。

本包是可信本地提交的真实流程测试，不是线上不可信代码托管。公开矩阵通过不证明未知缺陷不存在或工程最优。
