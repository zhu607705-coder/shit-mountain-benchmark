# 我方修复仓库

运行环境为Python 3.10+标准库。两个终端分别执行python3 manage.py serve和python3 manage.py worker，默认SQLite位于仓库runtime/ledger.sqlite3。LEDGER_DB可指定绝对路径或相对仓库路径，LEDGER_PORT可调整HTTP端口。

自家测试：python3 -B -m unittest -v test_submission.py。

从C1题目录运行python3 -B e2e_env_judge.py --submission repository/baseline --output repository_baseline_result.json，可执行真实HTTP/SQLite/worker全回归、同仓库核心回归和自测变异检查。DIAGNOSIS.md记录定位修复；TEST_REPORT.md记录实测。
