# Product Spec：AgentHub-Lite

## 目标

AgentHub-Lite 是一个以 IM 聊天为核心交互方式的多 Agent 协作平台。用户可以像使用群聊一样，与 Orchestrator、OpenCode、Codex、Custom Agent 等多个 Agent 协作，生成、修改、预览和部署项目产物。

## 比赛核心能力覆盖

| 比赛要求 | AgentHub-Lite 对应能力 |
|---|---|
| IM 聊天式交互 | `/agenthub` 页面：会话列表、消息流、输入框、右侧产物区 |
| 单聊模式 | 单个 Agent 会话 |
| 群聊模式 | Project Room，多 Agent 成员参与 |
| @Agent | 输入框选择或输入 Agent mention |
| 主 Agent 协调器 | Orchestrator 生成计划、分派步骤、汇总结果 |
| 多 Agent 接入 | OpenCode Adapter + Codex/Custom OpenAI Adapter |
| 自建 Agent | AgentProfile + system prompt + capability tags |
| 产物预览 | ArtifactCard / WebPreview / Markdown / Code |
| Diff | 真实文件变更产生 DiffCard |
| 部署 | Static host provider 返回真实可访问 URL |
| 上下文连续 | 会话消息和 AgentRun 记录由后端保存 |

## 最小演示闭环

```text
用户新建 Project 群聊
  -> @Orchestrator 提出任务
  -> Orchestrator 输出计划
  -> OpenCode 执行实现
  -> Reviewer Agent 审查
  -> 生成 Artifact / Diff
  -> 用户预览网页或文档
  -> 用户部署
  -> 返回 DeploymentCard
```

## 不做事项

- 不做完整多人实时编辑。
- 不做生产级权限体系。
- 不做完整容器云部署。
- 不做旧 Web 页面复活。
