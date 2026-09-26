# 账本服务仓库

buggy/为完整starter，baseline/为作者修复。两个仓库分别包含config.py（环境）、db.py（事务/schema/迁移）、service.py（接受/幂等/查询）、worker.py（领取/租约/完成）、api.py（HTTP）、manage.py（进程入口）、engine.py及配套核心模块、test_submission.py（提交者自测）。

核心来源：starter的engine/storage/projection来自原C1/buggy；作者基线engine/validation来自原C1/baseline。各仓库拥有自己的副本，运行时不跨目录导入参考答案。

从C1目录执行python3 -B e2e_env_judge.py --submission repository/baseline一键验证。手动进入任一仓库，分别启动python3 manage.py serve及python3 manage.py worker，默认相对数据库runtime/ledger.sqlite3。

默认无身份认证。tenant参数是本题的数据命名空间，不等同于生产身份授权；认证不属于已验证内容。
