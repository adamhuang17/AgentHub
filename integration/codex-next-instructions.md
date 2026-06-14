# Codex Next Instructions

下一步不要继续扩大后端能力，优先做真实联调验收。

## 优先级

1. 安装 Bun 后运行 `bun --cwd packages/app typecheck`。
2. 打开 `/agenthub`，确认前端没有编译错误。
3. 启动 AgentHub API，确认 UI 能读取真实 agents/conversations。
4. 启动 OpenCode HTTP service，确认 `@OpenCode` 能产生真实 AgentRun。
5. 生成真实 HTML 或 Markdown Artifact。
6. 验证 Deploy URL 可访问。

## 每次完成后必须报告

- 修改文件列表。
- 运行命令。
- 测试结果。
- 手动验收步骤。
- 失败项。
- 是否存在 fake success / hardcode / mock。

## 禁止

- 不要把旧 `AgentHub/apps/web` 作为产品页面。
- 不要写死 Agent 回复。
- 不要写死部署 URL。
- 不要在未运行 OpenCode service 时显示 OpenCode succeeded。
