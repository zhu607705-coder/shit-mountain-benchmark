# 两道前端开放解挑战

- **F1 凌晨事故控制台**：高密度信息、10,000条固定事件、虚拟列表、筛选、URL恢复、跨窗口状态与证据链。
- **F2 实验排程账本**：资源/依赖约束、本机持久化、撤销重做、离线、字段级三方合并与并发丢数据。

每题包含 `PROMPT.md`（发给模型）、`data.json`（固定事实）、`starter.html`（可运行故障版）、`baseline.html`（自家参考实现）、`rubric.md`（冻结前评审用）、`baseline.md`（基线边界）和 `verification.json`（实际验证证据）。`*.template.html` 是不嵌入大数据的易读源码。

从包根目录运行 `python3 -m http.server 8765`，打开：

- `http://127.0.0.1:8765/frontend/F1/baseline.html`
- `http://127.0.0.1:8765/frontend/F2/baseline.html`

可以直接打开单文件，但应使用 HTTP 做一致评测，尤其是多窗口、剪贴板和 origin存储场景。无需安装前端依赖，不请求外部网络。

重建页面：`python3 frontend/build_frontend.py`。语法与独立数据逻辑检查：`python3 frontend/verify_frontend.py`。它不会打开浏览器；完整端到端结果与截图由父级报告补充，未测场景不会伪装通过。

两份基线对跨窗口写入采取不同机制：F1 每事件独立键；F2 共享写锁与版本检查，有外部变化时拒绝覆盖并保留独立恢复副本。完整资格仍由公开场景实测决定；作者不自给视觉分，比赛可以从基线出发继续超越它。
