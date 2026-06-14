# Orchestrator Design

## 角色定位

Orchestrator 是 AgentHub-Lite 中的主 Agent，类似 PM/PMO。它负责理解用户目标、拆解任务、分派 Agent、聚合结果。

## TurnDecision

Orchestrator 不应使用本地关键词分类器冒充智能理解。它必须通过真实 configured provider 输出结构化决策。

```json
{
  "decision_type": "plan_task | direct_response | needs_clarification | no_action",
  "goal": "string | null",
  "steps": [
    {
      "id": "step-1",
      "kind": "analysis | implementation | review | deploy",
      "title": "string",
      "instruction": "string",
      "required_capabilities": ["frontend", "coding"],
      "depends_on": []
    }
  ]
}
```

## 调度规则

1. `mentions` 非空：优先分派给被 @ 的 Agent。
2. 群聊无 mention：交给 Orchestrator。
3. 单聊：默认发给当前 Agent。
4. 找不到匹配 Agent：step 进入 `blocked`，不得 fallback。
5. Planner 未配置：返回 `turn_router_not_configured`。

## 反假成功

- 不允许固定输出三步计划冒充真实 planner。
- 不允许 provider 未配置时 fallback 到 mock planner。
- 不允许 Agent 失败时由 Orchestrator 汇总成“全部完成”。
