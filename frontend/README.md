# 前端赛道 F1–F4

四题都以持续操作后的正确状态、可访问性和使用体验评分，布局与框架开放，没有唯一参考截图。

| 题号 | 任务 | 关键场景 |
|---|---|---|
| [F1](F1/PROMPT.md) | 凌晨事故控制台 | 10k列表、筛选/URL/选中身份、因果调查、确认持久化 |
| [F2](F2/PROMPT.md) | 实验排程账本 | 资源/依赖、编辑撤销、离线、三方冲突、多窗口恢复副本 |
| [F3](F3/PROMPT.md) | 持续变化的事故工作台 | 50k记录、版本/乱序/删除、暂停与全量筛选导出 |
| [F4](F4/PROMPT.md) | 多窗口离线排程 | 字段合并、补偿撤销、事件导入与删除墓碑 |

每题包含故障 starter.html 和可运行 baseline.html。F1/F2 的可读模板与固定数据通过 build_frontend.py 重建；F3/F4为自包含页面。

从根目录 `make preview` 后打开 `/frontend/F1/baseline.html`，更换F编号可浏览其它题。`./scripts/test.sh` 运行脚本语法和状态逻辑，不能代替完整浏览器验收或人工设计盲评。

F1/F2的rubric.md，以及F3/F4的semantic-rubric.md，描述公开任务场景。`tools/check_browser_smoke.py`、`tools/check_memory_smoke.py` 是参考页面专用辅助脚本，需要另行安装Python Playwright和浏览器；其中的DOM定位器不能作为自由布局作品的唯一正式裁判。两种测试环境输出分别标记，不能把内存模拟当成原生存储/下载证明。

本次原生HTTP抽测见根results/frontend_browser_verification.json和additional_browser_verification.json。完整质量分和独立视觉评分仍为null。
