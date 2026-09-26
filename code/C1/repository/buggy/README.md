# 账本服务starter

Python标准库，无需安装依赖。启动API：python3 manage.py serve；另一终端启动worker：python3 manage.py worker。LEDGER_DB默认runtime/ledger.sqlite3，LEDGER_PORT默认8000。python3 manage.py init可初始化数据库。

当前版本带有故障；先阅读INCIDENT.md，复现并定位。原smoke测试命令为python3 -B -m unittest -v test_submission.py。请修复服务并新增自己的回归测试，不要把smoke通过当成系统完成证明。

从C1题目录运行python3 -B e2e_env_judge.py --submission repository/buggy，查看完整环境/业务失败。
