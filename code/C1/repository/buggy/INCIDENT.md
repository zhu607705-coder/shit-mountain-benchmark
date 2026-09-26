# 已复现事故：接口绿灯，后台停滞

以下是repository/buggy实际运行信号，完整日志尾部在C1/repository_buggy_result.json。临时路径和端口动态分配。

复现：python3 -B e2e_env_judge.py --submission repository/buggy --output repository_buggy_result.json。

| 场景 | 症状 | 实测信号 |
|---|---|---|
| 旧库启动 | health称schema2，任务不完成 | sqlite3.OperationalError: no such column: claimed_at |
| 两个cwd | 提交202但worker看不到任务 | API/worker日志db路径分别在“别处 api”和“别处 worker” |
| worker被杀 | 新worker仍无法完成旧任务 | job持续processing直到等待超时 |
| 逆序撤销 | 请求成功但余额错误 | reverse先到、post后到的最终投影断言失败 |
| 租户并发 | 不同租户同request_id冲突 | POST /v1/batches返回409 REQUEST_CONFLICT |

正常单租户的提交/查询/统计以及正常重启仍能通过。排障需分别核对进程活性、schema就绪、队列进展、业务投影。不得通过删除恢复、幂等、隔离功能掩盖错误。
