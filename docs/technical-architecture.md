# Technical Architecture

## 架构总览

```text
AgentHub-Lite Product Entry
  ├─ OpenCode packages/app /agenthub 页面
  ├─ AgentHub Control Plane API
  ├─ OpenCode HTTP Adapter
  ├─ Codex / Custom Agent Adapter
  ├─ Artifact / Diff / Preview 服务
  └─ Static Deployment Provider
```

## 前端

前端位于：

```text
../opencode-dev/packages/app
```

关键文件：

```text
src/app.tsx
src/pages/agenthub.tsx
src/agenthub/types.ts
src/agenthub/api/agenthub-client.ts
```

设计原则：

- 不使用旧 AgentHub Web。
- 复用 OpenCode 已有 UI、布局和 workspace 能力。
- API 不可达时显示 `api_unreachable`，禁用发送。
- Artifact、Diff、Deploy 必须来自后端真实数据。

## 后端

后端位于：

```text
../AgentHub/services/api
```

关键模块：

```text
agents/
agent_runs/
conversations/
orchestration/
artifacts/
deployment/
shared/
```

## Adapter

### OpenCode HTTP Adapter

职责：

1. 检查 OpenCode service 健康状态。
2. 创建或复用 OpenCode session。
3. 发送 prompt。
4. 获取 assistant message。
5. 获取 diff / changed files。
6. 转换为 AgentRunEvent 与 Artifact。

### Codex / Custom OpenAI Adapter

职责：

- 作为第二 Agent 平台或自建 Agent provider。
- 未安装 CLI 或缺少 API Key 时明确失败。

## Artifact

Artifact 类型：

- `code_file`
- `markdown_doc`
- `web_preview`
- `source_diff`
- `deployment_release`

没有真实内容不得创建 Artifact。

## Deployment

Static host provider 必须真实复制文件，并在 URL 可访问后才能返回 `published`。
