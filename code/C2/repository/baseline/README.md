# 参考修复仓库

这是可启动的HTTP服务与独立worker，入口为cli.py，配置示例为example_config.json。详细挑战契约与环境矩阵见上两级C2/PROMPT.md。

从本目录开两个终端：

```bash
python3 cli.py serve --config example_config.json
python3 cli.py worker --config example_config.json
```

HTTP进程打印动态端口；base path为/build/v2。相对数据库位置以配置文件所在目录为基准。运行提交方自测：

```bash
python3 selftest.py
```

根因见DIAGNOSIS.md，实际复现、自测和全回归记录见TEST_REPORT.md。全套HTTP/数据库/重启验证从C2根目录运行e2e_env_judge.py。
