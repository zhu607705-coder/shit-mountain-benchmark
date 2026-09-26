# 评测设计参考

检索日期 2026-09-26。本包题面、缺陷实现与基线由本次任务编写，以下来源只用于评测方法背景，不作为本包实测结果来源。

- SWE-bench 官方 Evaluation Guide。以实际补丁和测试执行判断问题是否解决，并区分实验环境故障与未修复结果。
  https://www.swebench.com/SWE-bench/guides/evaluation/
- DesignBench，2025。前端生成、编辑与修复，多框架任务，不局限于静态网页生成。
  https://arxiv.org/html/2506.06251v1
- Vibe Code Bench，2026。以端到端用户工作流检查应用；规格应含通过测试所需信息。
  https://arxiv.org/html/2603.04601v1
- Playwright 官方 Visual comparisons。截图取决于操作系统、浏览器、硬件等，应固定渲染环境。
  https://playwright.dev/docs/test-snapshots
- W3C WCAG 2.2 Understanding Reflow / Keyboard。窄屏重排与键盘操作的评测依据。本包没有声称完整WCAG符合性。
  https://www.w3.org/WAI/WCAG22/Understanding/reflow.html
  https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html
