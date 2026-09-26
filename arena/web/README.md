# 比赛操作台

本目录是统一启动器的静态前端，连接同源 Arena API。入口为 `/`，资源为 `/app.js`、`/style.css`、`/icons/`。无需 CDN、npm、字体服务或构建步骤。应由项目 Arena 服务启动并提供 API。

操作顺序：选择题目和难度 → 抽取实例 → 查看三段任务或下载公开题包 → 填写选手与本机答案路径 → 封存并检验 → 查看案例、原分与同场相对分 → 下载 Codex 评阅任务。

## 实际接口

- `GET /api/bootstrap`：`csrf`、`tasks`、`tiers`、`matches`。
- `GET /api/matches`：最近场次。
- `POST /api/draw`：`{task_id,tier}`。
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

后台检验期间约每 1.4 秒刷新，其他时候约每 4 秒刷新，页面隐藏时降低频率。重新选题不会被当前比赛的状态轮询覆盖。不同场次的过期状态响应不会覆盖较新的选择。页面只在 sessionStorage 保留当前场次 ID，不存私有 seed、密钥、原始 reasoning 或用户答案文件。

## 视觉与图标来源

布局采用题目选择器、难度选项、任务阶段、提交表单、后台进度、结果表。参考官方 [shadcn blocks](https://ui.shadcn.com/blocks) 与 [Table 文档](https://ui.shadcn.com/docs/components/base/table) 的成熟工作台组织方式；未引入其运行时依赖或复制组件源码。

所有功能 SVG 图标直接取自 [Lucide 官方仓库](https://github.com/lucide-icons/lucide)，锁定 commit：

`66d8f9fc394b8530377e5f6112f0b8908ba01280`

图标逐文件 URL 和 SHA-256 在 [icons/SOURCE.json](icons/SOURCE.json)，原始许可保存在 [icons/LICENSE](icons/LICENSE)。SVG 文件未重新绘制，统一按 currentColor 蒙版显示，并配文字或可访问标签；重新连接使用 refresh-cw，抽签使用 shuffle。没有 shield-check 图标。

主屏保留必要字段和按钮，材料、规则及长实例承诺默认折叠。`prefers-reduced-motion` 会关闭旋转、脉冲和进度动画。表单可键盘使用，状态有 live region，README 使用原生 dialog，可按 Escape 关闭。

## 验证

```bash
node --check arena/web/app.js
```

开发期间还运行了 Node mock 响应检查，覆盖 GET/POST、CSRF、结构化 API 错误、partial/completed 区分、前端完整评阅 pending、案例状态和 null/0 区分。上述检查不替代真实服务和原生浏览器的完整 draw-submit-grade 流程；浏览器验收由主任务统一执行。
