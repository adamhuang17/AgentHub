# Known Limitations

## 当前真实能力

- `/agenthub` 页面作为比赛 IM 工作台入口。
- AgentHub Control Plane API 作为后端入口。
- OpenCode HTTP Adapter 作为真实 Coding Agent 接入路径。
- Static host provider 作为最小部署闭环。
- Artifact / Diff / Deploy 卡片只展示真实结果。

## 外部依赖

| 依赖 | 未满足时状态 |
|---|---|
| Bun | `bun_not_installed` |
| AgentHub API | `api_unreachable` |
| OpenCode HTTP service | `opencode_server_unavailable` |
| Codex CLI | `adapter_executable_not_found` |
| API Key | `missing_credentials` |
| Planner provider | `turn_router_not_configured` |

## 暂未完成

- 完整源码收敛到单一 monorepo。
- 完整桌面端与移动端。
- 完整多人实时协作。
- 生产级权限审计。
- 容器化云部署。
- 完整版本树和冲突解决 UI。

## 不应夸大的能力

不得声称：

- 已完成完整生产级 AgentHub。
- 已完成所有主流 Agent 平台接入。
- 已完成真实移动端。
- 已完成云平台全量部署。
- 已完成完整多人协作。
