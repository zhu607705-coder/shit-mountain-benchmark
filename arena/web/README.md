# 比赛操作台

本目录包含沉浸式抽题舞台与比赛空间，连接同源 Arena API。入口为 `/`，资源为 `/app.js`、`/motion.js`、`/room.js`、`/style.css`、`/room.css`、`/icons/`。无需 CDN、npm、字体服务或构建步骤。应由项目 Arena 服务启动并提供 API。

操作顺序：选择方向和难度 → 抽一道 → 服务端返回后揭晓题签 → 开始这题 → 查看三段任务或下载题包 → 封存并检验 → 查看案例、原分与相对分 → 下载 Codex 评阅任务。刷新进入未知题目的初始舞台；手动选题和历史场次放在次级菜单，提交与成绩放在工作抽屉。

## 实际接口

- `GET /api/bootstrap`：`csrf`、`tasks`、`tiers`、`matches`。
- `GET /api/matches`：最近场次。
- `POST /api/draw`：默认 `{task_id:"random",tier,track:"all"|"R"|"C"|"F"}`；手动模式仍传具体 task_id。题目只能由返回的真实场次决定。
- `GET /api/matches/:id/status`：场次、`public_scope`、提交和后台 job。
- `POST /api/matches/:id/submit`：`{participant,source_path,entrypoint,metrics_path?}`，返回提交对象。
- `POST /api/matches/:id/grade`：`{submission_id}`，启动后台检验。
- `POST /api/matches/:id/cancel`：`{job_id}`。
- `GET /api/matches/:id/report`：提交报告和逐案例结果。
- `GET /api/matches/:id/leaderboard`：同场相对成绩。
- `/api/matches/:id/download` 与 `/grading-request`：公开题包和 Codex 评阅任务。

所有 POST 使用 bootstrap 返回的 `X-Arena-CSRF`。错误从 `{error:{code,message}}` 读取，使用纯文本显示。选手名、题目、提示词、服务端消息均经 DOM textContent 渲染。

题目、六档真实范围、数据规模、案例次数与预算来自服务端。三段任务读取 `public_scope.prompt_segments` 的 `scope/materials/deliverables/budget/prompt`，没有独立编造难度数字或成绩。任务 README 可以复制或保存为本地 Markdown。

## 状态和评分范围

- `valid` 表示基础合法，`completed` 表示全部所选检查完成；合法但未完成的结果显示“部分完成”。
- `valid=true` 且 `completed=true` 时，R 类开放优化题显示“合法完成”，由实际原分表达质量；C 类全部所选检查完成才显示“自动通过”。
- 前端自动通过显示“语义通过 · 完整评阅待定”，不用绿色完整通过替代 UI 评阅。
- 效率只有在 API 返回 `efficiency_eligible=true` 时显示实际 `efficiency_score`，否则显示“待核验”。
- 原分和相对分由 API 提供；空态不填模拟记录，null 显示“待评”，实际 0 保留为 0。
- 前端场次冠军仅显示“语义领先”，完整 UI 冠军不由前端页面推断。
- 后台 `diagnostic=true` 的复跑标明“诊断复验”；官方冻结成绩仍来自服务端报告。

后台检验期间约每 1.4 秒刷新，其他时候约每 4 秒刷新，页面隐藏时降低频率。用户加载另一场时取消旧轮询，旧异步响应不能覆盖新选择；提交与判分响应也绑定原场次。页面不保存私有 seed、密钥、原始 reasoning 或用户答案文件。

## 开始后的四个场景

`ArenaRoom` 管理任务、提交、检验、战报四个 view；现有 `ArenaUI` 继续拥有实际提交、服务状态和报告。room 不计算新的成绩，也不修改判分。

- 任务：大阶段编号与三段提示词切换，长判定范围、材料和交付收进详情。
- 提交：答案纸与投递口构图，保留实际目录/文件入口和性能证据表单。
- 检验：扫描动画只在真实执行阶段运行；正在执行第 N 组不代表 N 组已经完成，未知进度不显示虚构百分比。“检验用时”是裁判耗时。
- 战报：只有 C 题 `valid=true`、`completed=true` 且分数有效时显示本档通过；R 是策略评估，F 是语义结果并保留完整 UI 待评。失败 0 分与未知 null 保持区别。

`watchJob(id)` 仅跟踪用户实际启动的 job。新结果等待 grade_id 对齐，明确 null 不回退到旧分；诊断复验保留首次官方分。轮询和历史加载不会重播胜利。揭示回调绑定 match/job 并可取消，关闭、换场或 reduced-motion 变化立即停止。若检验在任务页关闭期间结束，不弹窗；再次进入同场直接显示战报。

图片示例来自真实本地控制候选：[任务](../../docs/images/mission-briefing.png)、[通过](../../docs/images/mission-success.png)、[部分完成](../../docs/images/mission-partial.png)，不作为商业模型比赛成绩。

## 视觉与图标来源

主画面采用黑底、荧光黄、暖白悬浮签卡、巨幅文字、硬边切面与少量 halftone。抽签后，R/C/F 分别切换平行斜切、交叉斜撑和正交切面的不同轮廓；其变化不依赖颜色。视觉方向参考 [Pentagram Shakespeare in the Park 2016](https://www.pentagram.com/work/shakespeare-in-the-park-2016)、[GSAP Showcase](https://gsap.com/showcase/) 与 [Made With GSAP 的公开鼠标卡片说明](https://madewithgsap.com/effects/tutorial025)，没有复制其素材、付费代码或运行时依赖。工作抽屉沿用选择器、步骤与结果表等常规交互结构。

所有功能 SVG 图标直接取自 [Lucide 官方仓库](https://github.com/lucide-icons/lucide)，锁定 commit：

`66d8f9fc394b8530377e5f6112f0b8908ba01280`

图标逐文件 URL 和 SHA-256 在 [icons/SOURCE.json](icons/SOURCE.json)，原始许可保存在 [icons/LICENSE](icons/LICENSE)。SVG 文件未重新绘制，统一按 currentColor 蒙版显示，并配文字或可访问标签；重新连接使用 refresh-cw，抽签使用 shuffle。没有 shield-check 图标。

主屏只保留方向、难度和抽题；材料、规则与长实例承诺在二级界面。motion.js 使用 requestAnimationFrame 合帧及有界差动响应，指针离开后收敛回位并停止帧循环。粗指针/触屏静态，prefers-reduced-motion 关闭动作。充能、洗牌、揭示三态以真实 API 结果为边界；失败保留上题并恢复操作。按钮在请求与揭示期间禁用。舞台使用 overflow:clip，避免焦点滚入导致内部画面移动。表单可键盘操作，原生 dialog 支持 Escape。

## 验证

```bash
node --check arena/web/app.js
node --check arena/web/motion.js
node --check arena/web/room.js
node --test arena/web/test_room.cjs
```

开发期间还运行了 Node mock 响应检查，覆盖 GET/POST、CSRF、结构化 API 错误、partial/completed 区分、前端完整评阅 pending、案例状态和 null/0 区分。上述检查不替代真实服务和原生浏览器的完整 draw-submit-grade 流程；浏览器验收由主任务统一执行。

额外 Node 模拟时钟测试覆盖三阶段时序、揭示前身份不变、R/C/F 几何配置差异、rAF 收敛与回位、reduced-motion/触屏静态和揭示取消。真实浏览器发现的方向事件冒泡、舞台内部滚动、手机按钮换行问题已分别通过限定按钮选择器、overflow:clip、两行底部控件修复；最终屏幕与端到端证据由主任务记录。
