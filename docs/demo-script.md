# Demo Script：3-5 分钟演示流程

## 演示前检查

1. `AgentHub-Lite/scripts/check-layout.ps1` 通过。
2. `AgentHub-Lite/scripts/check-api.ps1` 通过。
3. OpenCode HTTP service 已启动。
4. OpenCode Web App 已启动。
5. 打开 `/agenthub`。
6. 至少两个 Agent 状态为真实 ready 或明确显示 not_configured。

## 演示流程

### 1. 展示 IM 工作台

说明：AgentHub-Lite 以 IM 作为核心交互范式，左侧是会话，中间是聊天流，右侧是 Agent 和产物。

### 2. 新建 Project 群聊

创建一个 Project Room，展示 Orchestrator、OpenCode、Reviewer 等 Agent 成员。

### 3. 输入任务

示例：

```text
@Orchestrator 请帮我生成一个 AgentHub 多代理协作平台的落地页，包含核心能力介绍、技术架构和部署入口。
```

### 4. Orchestrator 计划

展示 Plan Card：

- analysis：整理页面结构。
- implementation：交给 OpenCode 生成页面。
- review：交给 Reviewer 检查内容和可用性。
- deploy：生成预览 URL。

### 5. OpenCode 执行

展示 OpenCode AgentRunCard 和 assistant message。

如果 OpenCode 不可达，必须展示 `opencode_server_unavailable`，不要强行演示成功。

### 6. Artifact 预览

展示 WebPreviewCard / MarkdownCard / CodeCard。

点击右侧预览区查看产物。

### 7. Diff 展示

要求修改局部内容，例如：

```text
把首屏标题改得更像比赛项目介绍，并补充“主 Agent 调度”说明。
```

有真实文件变更后展示 DiffCard。

### 8. 部署

点击部署，展示 DeploymentCard。

只有 URL 可访问后才显示 `published`。

### 9. 总结答辩口径

AgentHub-Lite 不是普通聊天壳，而是基于 OpenCode Runtime 的 IM 式多 Agent 产物协作平台。它用 Orchestrator 做任务拆解，用 Adapter 接入不同 Agent，用 Artifact 承载代码、Diff、预览和部署结果。

## 失败时演示口径

如果某个 provider 未配置，展示错误卡并说明：系统遵守 no fake success，不会伪造 Agent 成功或部署成功。
