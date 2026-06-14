# Acceptance Checklist

## 工程形态

- [ ] `AgentHub-Lite/` 与 `AgentHub/`、`opencode-dev/` 同级。
- [ ] `scripts/check-layout.ps1` 通过。
- [ ] README 明确说明当前是方案 A，不是完整源码搬迁。
- [ ] 旧 `AgentHub/apps/web` 没有被作为产品页面使用。

## 启动

- [ ] `scripts/dev-api.ps1` 能启动后端，或明确报错。
- [ ] OpenCode HTTP service 已真实启动。
- [ ] `scripts/dev-web.ps1` 能启动前端，或明确 `bun_not_installed`。
- [ ] `/agenthub` 页面可打开。

## 比赛核心能力

- [ ] 会话列表。
- [ ] 单聊。
- [ ] 群聊。
- [ ] @Agent。
- [ ] Orchestrator Plan Card。
- [ ] 至少两个 Agent 平台或一个平台 + 自建 Agent。
- [ ] ArtifactCard。
- [ ] DiffCard 只在真实 diff 存在时展示。
- [ ] Preview 可打开真实产物。
- [ ] Deploy 成功后 URL 可访问。

## 反 fake success

- [ ] 后端关闭时显示 `api_unreachable`。
- [ ] OpenCode 关闭时显示 `opencode_server_unavailable`。
- [ ] 缺少凭据时显示 `missing_credentials`。
- [ ] Planner 未配置时显示 `turn_router_not_configured`。
- [ ] 未生成 diff 时不显示 DiffCard。
- [ ] 部署失败时不显示 `published`。
