# Migration Boundary：方案 A 工程边界

## 当前策略

方案 A 不搬迁源码，只新增 `AgentHub-Lite/` 作为统一产品入口层。

这是为了避免在比赛短周期内破坏 OpenCode workspace，同时解决之前“项目下面仍然只有 AgentHub 和 opencode-dev，看起来不是新产品”的问题。

## 目录关系

```text
父目录/
  AgentHub/        # 后端 Control Plane，复用旧 AgentHub 后端能力
  opencode-dev/    # OpenCode 前端与 Agent Runtime 基座
  AgentHub-Lite/   # 新增统一产品入口层
```

## 属于最终产品能力的代码

### 前端

当前位于：

```text
../opencode-dev/packages/app/src/pages/agenthub.tsx
../opencode-dev/packages/app/src/agenthub/
```

这些代码属于 AgentHub-Lite 的前端实现，但保留在 OpenCode workspace 内，避免依赖断裂。

### 后端

当前位于：

```text
../AgentHub/services/api/
```

重点模块包括：

```text
agents/
agent_runs/
conversations/
orchestration/
artifacts/
deployment/
shared/
```

这些代码属于 AgentHub-Lite 的后端 Control Plane。

## 明确废弃

```text
../AgentHub/apps/web
```

旧 Web 不能作为比赛产品页面，也不能继续在其上堆功能。

## 暂不迁移原因

OpenCode 前端和运行时依赖内部 workspace 包。若立即复制到 `AgentHub-Lite/apps/web`，需要同步迁移：

- `packages/ui`
- `packages/sdk`
- `packages/config`
- 构建脚本
- workspace 配置
- Vite/Bun/路径别名

这会增加构建失败风险，不符合当前“尽快完成比赛 Demo”的目标。

## 后续可选方案 B

功能稳定后，可以再做源码收敛：

```text
AgentHub-Lite/
  apps/web/       # 从 OpenCode packages/app 收敛
  services/api/   # 从旧 AgentHub services/api 收敛
  packages/shared/
```

方案 B 必须在前端 typecheck 和浏览器验收通过后再做。
