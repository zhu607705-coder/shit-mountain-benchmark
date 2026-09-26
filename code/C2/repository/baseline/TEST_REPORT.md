# 实跑测试报告

测试对象为这个仓库目录。核心裁判通过仓库根engine.py导出实际worker使用的app.core.engine.Engine，避免测试对象与运行对象分离。

## 复现

在C2根目录实际执行：

```bash
python3 e2e_env_judge.py --submission repository/buggy --output repository_buggy_result.json
python3 judge.py --submission repository/buggy --output repository_core_buggy_result.json
```

旧仓库环境矩阵3/11通过，失败包括basepath、分离工作目录、项目隔离、取消、依赖错误恢复、快照、worker重启恢复和旧schema升级；环境valid=false。核心2/57通过，核心valid=false。详细错误与真实测量保存于对应JSON。

## 修改后自测

```bash
python3 repository/baseline/selftest.py
```

8/8实际通过，退出码0，日志存C2根目录的repository_selftest_result.json。测试覆盖：配置文件相对路径、basepath规范化、入队payload冻结、跨项目查询404、取消优先于结果发布、running恢复、同一Engine导出及旧schema无损升级。

这些是可复跑的提交方自测，不是仅写一个测试计划。自测质量是否满足10分评分锚点仍由主办方另行核验，当前selftest_score=null。

## 全回归

```bash
python3 e2e_env_judge.py --submission repository/baseline --output repository_baseline_result.json
python3 judge.py --submission repository/baseline --output repository_core_baseline_result.json
python3 -m unittest -v test_harness.py
```

真实环境矩阵11/11通过，environment_score=70、valid=true；同份仓库核心57/57通过、valid=true，仓库换算核心分20。裁判自身4项回归也通过。环境测试实际运行服务器和worker，发送HTTP请求，使用临时SQLite，实施进程中断与重启，最后自动清理。

已验证机器小计90/90。完整raw_score与自测质量分暂为null，不自评总分，也不声称最优。每次重跑的时间与源码哈希以最新结果JSON为准。
