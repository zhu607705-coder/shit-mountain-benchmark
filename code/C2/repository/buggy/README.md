# 参赛起始仓库

先读C2/INCIDENT.md和PROMPT.md，再实际启动、复现、定位、修复与自测。

```bash
python3 cli.py serve --config example_config.json
python3 cli.py worker --config example_config.json
```

需要两个终端；服务器打印动态端口。配置和进程能启动不代表整体业务正常，换目录、取消、改图、恢复及升级已有数据库也是题目验收内容。请从本目录复制或创建补丁，保留业务接口与已有数据。
