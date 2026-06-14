# Runtime Dependencies

## 必需

| 依赖 | 用途 | 缺失时 |
|---|---|---|
| Python | 启动 AgentHub Control Plane API | 后端无法启动 |
| Bun | 启动 OpenCode packages/app | `bun_not_installed` |
| OpenCode HTTP service | 真实 Coding Agent Runtime | `opencode_server_unavailable` |

## 可选

| 依赖 | 用途 | 缺失时 |
|---|---|---|
| Codex CLI | 第二主流 Agent 平台 | `adapter_executable_not_found` |
| Claude Code CLI | 可选 Agent 平台 | `adapter_executable_not_found` |
| OpenAI-compatible API Key | Planner / Custom Agent | `missing_credentials` |
| Static deploy root | 本地部署 | `deployment_failed` |

## 环境变量

见根目录 `.env.example`。

## 检查命令

```powershell
./scripts/check-layout.ps1
./scripts/check-api.ps1
./scripts/check-web.ps1
```
