# AgentHub

> 以 IM 为入口的多 Agent 产物协作平台。用户在会话中提出目标、选择或 `@` 指定 Agent，由 Orchestrator 拆解任务、调度 Agent 执行，并将代码、网页、文档、Diff、文件和发布结果沉淀为可预览、可编辑、可追踪、可审计的产物。

---

## 1. 项目定位

AgentHub 的目标是把“多人协作式 IM 体验”和“多 Agent 产物执行能力”结合起来，让用户可以像在飞书、微信或 Slack 中协作一样，与多个 AI Agent 一起完成真实产物。

用户只需要在会话里描述目标，系统会根据上下文判断应该直接回答、拆解任务、请求澄清，还是等待用户继续输入。复杂任务会进入 Orchestrator，由系统生成可追踪的 Plan 和 Step，并分派给不同 Agent 执行。

核心目标：

- 用 IM 会话承载自然交互。
- 用 Orchestrator 承担任务拆解与 Agent 分派。
- 用 AgentRun 记录每一次 Agent 执行。
- 用 Adapter Gateway 接入不同 Agent 后端。
- 用 Artifact 承载最终代码、文档、网页、Diff 和发布结果。
- 用权限与审计保证高风险操作可控、可回溯。

---

## 2. 飞书文档内容详细展示

以下为项目文档飞书文档链接。

| 文档 | 内容 | 链接 |
| --- | --- | --- |
| 产品说明文档 | 项目背景、目标用户、核心场景、功能边界 | `https://my.feishu.cn/docx/Sq9wd5nnqoHtpvx6pF1cDWIhnvf?from=from_copylink` |
| 技术设计文档 | 架构设计、模块边界、核心协议、数据模型 | `https://my.feishu.cn/wiki/RzyIwDoRZi9iAgkGng8cUVRLnuh?from=from_copylink` |
| 演示脚本文档 | 答辩演示流程、核心话术、异常场景展示 | `https://my.feishu.cn/wiki/SHqVwAcZ1iVkAGklLRtcXxQAnTg?from=from_copylink` |
| AI 协作记录 | 使用 AI 完成需求拆解、架构设计、编码与测试的过程记录 | `https://my.feishu.cn/wiki/WATawS1AWimrjmkefEvc4N6YnXc?from=from_copylink` |

---

## 3. 产品主链路

AgentHub 的完整工作流如下：

```text
用户消息
  -> 会话与上下文持久化
  -> Turn Routing 判断消息意图
  -> Orchestrator 任务拆解
  -> Agent 能力匹配与权限判定
  -> AgentRun 执行
  -> Adapter 调用真实后端
  -> AgentRunEvent 记录执行过程
  -> Artifact 生成与版本化
  -> Diff 预览与应用
  -> 网页 / 文档 / 代码产物预览
  -> 发布到真实目标平台
  -> 会话流返回结果与执行记录
```

这个链路保证用户看到的不只是一次性回复，而是一套完整的产物执行过程：任务从哪里来、由谁处理、执行了什么、生成了什么、是否经过确认、最终结果在哪里。

---

## 4. 核心使用场景

### 4.1 私聊 Agent：简单问答

用户可以直接进入某个 Agent 的私聊会话，提出简单问题。

```text
用户：解释一下 JWT 的工作原理。
```

系统行为：

```text
消息持久化
  -> TurnDecision(direct_response)
  -> 创建 AgentRun
  -> 调用目标 Agent Adapter
  -> 写入 assistant message
  -> 记录 run events
```

该场景不会创建 Task、Plan 或 Artifact，适合知识问答、解释、总结、轻量分析。

---

### 4.2 群聊中 `@Agent`：指定 Agent 执行

用户可以在群聊中显式指定某个 Agent。

```text
用户：@CodeAgent 帮我检查这段登录逻辑有没有问题。
```

系统行为：

```text
消息持久化
  -> 解析 mentions
  -> 指定目标 Agent
  -> direct_response 或 plan_task
  -> 创建 AgentRun 或 PlanStep
  -> 返回执行结果
```

`@Agent` 适合用户明确知道要让哪个 Agent 处理的场景，例如代码检查、文档润色、需求分析、测试建议等。

---

### 4.3 Orchestrator 自动拆解复杂任务

当用户提出复杂目标时，Orchestrator 会将任务拆解为多个步骤。

```text
用户：帮我分析需求，设计页面结构，实现登录页，并检查代码问题。
```

系统行为：

```text
TurnDecision(plan_task)
  -> 创建 Task
  -> 创建 Plan
  -> 拆解 PlanStep
  -> 匹配 Agent 能力
  -> 分派给不同 Agent
  -> 执行并记录事件
```

示例 Plan：

```text
Step 1: analysis        -> 需求分析 Agent
Step 2: implementation  -> 代码实现 Agent
Step 3: review          -> 代码审查 Agent
```

用户可以在会话中看到每个步骤的状态、执行者、失败原因和产物结果。

---

### 4.4 产物生成与预览

Agent 执行结果不会只停留在聊天文本中，而是会被沉淀为 Artifact。

Artifact 可以是：

- 源码文件。
- 代码补丁。
- 网页预览。
- 文档。
- PPT 或结构化报告。
- 压缩包。
- 部署记录。
- 执行报告。

用户可以打开 Artifact 进行预览、下载、查看版本历史，或进入 Diff 视图进行变更确认。

---

### 4.5 Diff 应用与发布

涉及代码或文件修改时，Agent 不直接覆盖主工作区。

推荐流程：

```text
Agent 在 run workspace 中生成修改
  -> 系统生成 Diff
  -> 用户查看变更
  -> 权限检查
  -> 用户确认应用
  -> 创建新版本 Artifact
```

网页类产物可以进一步进入预览和发布流程：

```text
Artifact
  -> Preview
  -> Build
  -> Publish
  -> 返回真实 URL
  -> 写入 deployment release 记录
```

---

## 5. 核心模块

### 5.1 Conversations

会话模块负责承载 AgentHub 的 IM 交互体验。

主要能力：

- 创建会话。
- 会话列表展示。
- 单聊与群聊。
- 会话成员管理。
- 消息持久化。
- 回复、引用、pin 和上下文追踪。
- 刷新后恢复历史消息和执行状态。

核心对象：

```text
conversation
conversation_member
message
message_reference
pinned_context
conversation_summary
```

---

### 5.2 Turn Routing

Turn Routing 负责判断每条消息应该进入哪条产品路径。

统一决策类型：

```text
no_action
直接保存消息，不触发 Agent。

direct_response
目标 Agent 直接回答，不创建任务计划。

plan_task
进入 Orchestrator，创建任务、计划和步骤。

needs_clarification
请求用户补充信息，不创建任务。
```

Turn Routing 不负责生成最终回答正文，也不允许伪造 Agent 回复。它只产生结构化决策。

---

### 5.3 Orchestrator

Orchestrator 是复杂任务的编排核心。

主要能力：

- 接收 `plan_task` 决策。
- 生成 Task / Plan / PlanStep。
- 根据 Step 类型和能力标签匹配 Agent。
- 记录分派来源和分派原因。
- 标记 blocked step。
- 为后续执行和恢复提供结构化状态。

核心对象：

```text
task
plan
plan_step
step_dependency
```

---

### 5.4 Agents

Agent 模块负责维护平台中的 Agent 联系人和能力信息。

每个 Agent 包含：

- 名称。
- 头像。
- provider。
- 能力标签。
- 支持的产物类型。
- 可用工具。
- 风险等级。
- 是否启用。
- Adapter 健康状态。

Agent 在前端表现为联系人，在后端表现为可被 Orchestrator 调度的执行者。

---

### 5.5 AgentRun

AgentRun 是每次 Agent 执行的统一记录。

它可以来自两类入口：

```text
message -> direct_response
plan_step -> planned_step
```

AgentRun 记录：

- 执行来源。
- 目标 Agent。
- run mode。
- 当前状态。
- 错误码。
- 创建时间与更新时间。
- 执行事件。

典型状态：

```text
created
running
succeeded
failed
timed_out
cancelled
```

---

### 5.6 Adapter Gateway

Adapter Gateway 负责接入不同执行后端，并统一它们的输出。

规划支持：

```text
custom_openai
用于普通自定义大模型问答 Agent，可接 OpenAI-compatible API。

codex_cli
用于调用本地 Codex CLI。

claude_code_cli
用于调用本地 Claude Code CLI。

custom_agent
用于用户自建 Agent。
```

Adapter 的任务是：

- 将统一 AgentRunRequest 转换为后端调用格式。
- 将后端输出转换为 AgentRunEvent。
- 管理 health / preflight / timeout / cancel。
- 标准化错误。
- 禁止未配置后端伪造成成功。

---

### 5.7 Artifact

Artifact 是 AgentHub 的产物核心。

所有重要输出都应该进入 Artifact，而不是只放在聊天记录里。

Artifact 支持：

- 版本化。
- 下载。
- 预览。
- 父子关系。
- 与 AgentRun 关联。
- 与 Diff / Patch / Deployment 关联。

Artifact 让平台能够回答：

```text
这个产物是谁生成的？
来自哪个任务？
由哪个 Agent 执行？
是否修改过？
能否回滚？
是否发布过？
```

---

### 5.8 Permissions & Audit

权限与审计模块用于控制高风险操作。

高风险操作包括：

- 应用 Diff。
- 覆盖文件。
- 删除文件。
- 执行 shell 命令。
- 读取凭据。
- 发布到外部平台。

系统需要记录：

- 操作发起者。
- 执行 Agent。
- 目标 Artifact。
- 审批结果。
- 操作时间。
- 最终状态。

---

## 6. Agent 后端接入方式

### 6.1 custom_openai

`custom_openai` 用于接入普通大模型问答 Agent。

适用场景：

- 简单问答。
- 文本总结。
- 需求解释。
- 文档润色。
- 轻量分析。

可接入：

- OpenAI-compatible API。
- DeepSeek。
- 智谱。
- 豆包。
- Qwen。
- 其他兼容服务。

该 Adapter 不直接修改 workspace，不创建 Diff，也不发布产物。

---

### 6.2 codex_cli

`codex_cli` 用于接入本地 Codex CLI。

direct response 采用只读模式：

```text
codex -a never exec
  --json
  --cd <workspace_dir>
  --skip-git-repo-check
  --sandbox read-only
  --ephemeral
  --color never
  <prompt>
```

安全边界：

- direct_response 固定 read-only。
- 不使用 `danger-full-access`。
- 不自动应用代码修改。
- 不创建 Artifact / Diff / Deploy。
- 失败时不创建 assistant message。

---

### 6.3 claude_code_cli

`claude_code_cli` 用于接入本地 Claude Code CLI。

direct response 禁用写工具：

```text
claude -p <prompt>
  --output-format stream-json
  --verbose
  --no-session-persistence
  --permission-mode dontAsk
  --tools=
  --strict-mcp-config
```

安全边界：

- 禁用 Edit / Write / Bash / MCP 写工具。
- 由 AgentHub 控制 timeout。
- 不等待 CLI 无限 retry。
- 失败时不创建 assistant message。
- 不创建 Artifact / Diff / Deploy。

---

## 7. 错误处理原则

AgentHub 不允许 fake success。

当外部后端不可用时，系统必须明确记录错误，而不是假装执行成功。

典型错误：

```text
provider_not_configured
missing_credentials
credential_invalid
adapter_executable_not_found
adapter_auth_missing
adapter_auth_unusable
adapter_timeout
backend_auth_failed
backend_network_failed
backend_rate_limited
backend_unknown_error
```

失败路径必须满足：

- 不写 `run_succeeded`。
- 不写 fake assistant answer。
- 不创建成功状态 Artifact。
- 不隐藏错误。
- 保留可恢复提示。

---

## 8. 产物闭环

AgentHub 的最终目标不是“聊完即结束”，而是形成产物闭环。

完整闭环：

```text
用户提出目标
  -> Agent 执行
  -> 生成文件或内容
  -> 保存 Artifact
  -> 生成 Diff
  -> 用户确认
  -> 应用修改
  -> 预览结果
  -> 发布产物
  -> 保留审计记录
```

这使 AgentHub 可以从简单问答工具升级为可长期使用的 AI 产物协作平台。

---

## 9. 预期展示效果

在最终演示中，用户可以看到：

1. 创建一个项目会话。
2. 在群聊中 `@` 指定 Agent。
3. Orchestrator 自动拆解复杂任务。
4. 多个 Agent 分别执行分析、实现和审查。
5. 执行过程以 run timeline 展示。
6. 代码或文档产物以 Artifact 卡片出现。
7. 用户打开 Diff 预览修改。
8. 用户确认应用变更。
9. 网页产物进入预览或发布。
10. 失败场景显示明确错误和恢复入口。

---

## 10. 项目边界

AgentHub 明确不做以下事情：

- 不把未配置的后端伪造成可用。
- 不用 mock success 代替真实执行。
- 不把失败的 CLI 输出当作成功回答。
- 不让 Adapter 直接修改主 workspace。
- 不绕过权限系统应用 Diff。
- 不把凭据暴露到前端或消息内容。
- 不依赖关键词硬编码决定任务路径。

---

## 11. 最终目标

AgentHub 最终要交付的是一个可运行、可展示、可追踪的多 Agent 协作产品。

它应满足：

- 用户能在 Web IM 中创建会话、选择 Agent、发送任务。
- Agent 能进行直接问答和任务执行。
- Orchestrator 能拆解复杂任务并解释分派原因。
- 每个任务都有 Plan、Step、Run、Event 记录。
- 代码、文档、网页和文件结果能作为 Artifact 管理。
- 代码变更能通过 Diff 展示并由用户确认应用。
- 网页产物能预览并发布到真实目标。
- 后端未配置、凭据失效、执行失败、发布失败时都有明确错误状态。
- 所有高风险操作都有权限检查和审计记录。
