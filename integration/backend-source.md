# Backend Source Integration

## 当前后端源位置

```text
../AgentHub/services/api
```

## 关键入口

```text
../AgentHub/services/api/app/main.py
```

## 关键模块

```text
agents/
agent_runs/
conversations/
orchestration/
artifacts/
deployment/
shared/
```

## 关键接口

```text
GET  /health
GET  /api/agents
POST /api/agents
GET  /api/conversations
POST /api/conversations
GET  /api/conversations/{id}/messages
POST /api/conversations/{id}/messages
GET  /api/artifacts/{id}
POST /api/artifacts/{id}/preview
POST /api/artifacts/{id}/deploy
GET  /api/agents/{id}/adapter-health
GET/HEAD /static-deployments/...
```

## 后端要求

1. 未配置 provider 返回 `provider_not_configured`。
2. 缺 API Key 返回 `missing_credentials`。
3. OpenCode service 不可达返回 `opencode_server_unavailable`。
4. Planner 未配置返回 `turn_router_not_configured`。
5. 部署失败返回 `deployment_failed`。
6. 不允许捕获错误后继续成功流程。
