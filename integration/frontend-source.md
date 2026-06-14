# Frontend Source Integration

## 当前前端源位置

```text
../opencode-dev/packages/app
```

## AgentHub-Lite 相关文件

```text
../opencode-dev/packages/app/src/app.tsx
../opencode-dev/packages/app/src/pages/agenthub.tsx
../opencode-dev/packages/app/src/agenthub/types.ts
../opencode-dev/packages/app/src/agenthub/api/agenthub-client.ts
```

## 为什么不搬迁

OpenCode app 依赖 workspace 内多个包，短期内搬迁可能破坏构建。方案 A 只提供统一入口与脚本。

## 前端要求

1. 不使用旧 AgentHub Web。
2. 后端不可达时显示 `api_unreachable`。
3. 不用本地 hardcoded agents 冒充真实数据。
4. Artifact、Diff、Deployment 卡片必须来自 API。
5. 空状态可以显示，但必须是 `not_connected` / `waiting_for_backend` / `no_runtime_result`。

## 后续收敛条件

只有在以下条件满足后，才考虑迁移到 `AgentHub-Lite/apps/web`：

- `bun --cwd packages/app typecheck` 通过。
- `/agenthub` 页面浏览器验收通过。
- OpenCode app 的 workspace 依赖清单明确。
