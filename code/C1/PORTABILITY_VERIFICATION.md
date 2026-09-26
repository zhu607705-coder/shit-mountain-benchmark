# C1 本地服务可移植性修复验证

远端首轮macOS证据显示环境0/7，全部在serve readiness阶段urlopen超时且启动日志为空；同次核心63/63、自家测试5/5且5个变异全部被杀。该证据不能单独证明是代理或反向DNS导致，本次不宣称CI根因已经确认。

本次补充3个受控回归，并实际先观察失败，再修复到通过：

1. 环境与系统proxy发现函数都配置不可用的127.0.0.1:1，强制不绕过代理。旧harness健康请求失败；新harness使用只为127.0.0.1临时服务创建的ProxyHandler({}) opener，健康请求通过。
2. 将socket.getfqdn替换为抛AssertionError的resolver。baseline和buggy旧HTTPServer构造均在stdlib server_bind调用getfqdn处失败。两份API现在使用TCPServer.server_bind并直接设置localhost/端口，不需要反向DNS，测试通过。业务逻辑、资格门槛和原有缺陷未改。
3. 临时manage.py打印startup exploded并退出7。旧readiness只报告连接失败；新版报告pid、exit_code=7及日志。超时仍附进程状态和日志，未放宽1.2秒readiness或0.4秒请求阈值。

在本题目录复现：

```sh
python3 -B -m unittest -v test_harness.py
python3 -B judge.py --submission repository/baseline --output repository_baseline_core_result.json
python3 -B judge.py --submission repository/buggy --output repository_buggy_core_result.json
python3 -B e2e_env_judge.py --submission repository/baseline --output repository_baseline_result.json
python3 -B e2e_env_judge.py --submission repository/buggy --output repository_buggy_result.json
```

本机test_harness共7项通过（4个原oracle锚点+3个可移植性回归）。完整E2E另外在http_proxy/https_proxy及其大写变量全部指向127.0.0.1:1、no_proxy/NO_PROXY清空的子进程环境下实跑。

结果：baseline 7/7，valid=True，原分100.0，耗时2.080秒；buggy 2/7，valid=False，原分23.174603，耗时5.190秒。两份core仍分别63/63与10/63。

两份E2E和两份core JSON已保存到题目录，submission_sha256逐项核对当前仓库源码一致。下一轮远端Ubuntu/macOS CI仍需实际运行确认；本机受控回归不能替代远端验证。
