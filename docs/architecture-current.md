# AgentHub Current Architecture

> 只描述当前真实实现，不写未来愿景。

## 整体结构

```
AgentHub/
├── apps/web/           # Node.js 静态前端 (纯 HTML + vanilla JS)
│   ├── app.js          # 前端逻辑: 消息渲染、API 客户端、卡片系统
│   ├── index.html      # 单页 HTML + 内联 CSS
│   ├── server.mjs      # 开发服务器 (静态文件托管)
│   └── app.test.mjs    # 34 个前端单元测试
├── services/api/app/   # Python 标准库 HTTP API
│   ├── main.py         # ThreadingHTTPServer + 路由分发
│   ├── conversations/  # 会话、消息、成员管理
│   ├── agents/         # Agent 注册、Adapter 调用、健康检查
│   ├── agent_runs/     # AgentRun 执行引擎
│   ├── artifacts/      # 制品存储、版本、Diff、Patch
│   ├── memory/         # ContextBuilder + Pin 系统
│   ├── orchestration/  # Orchestrator、Planner、Turn Router
│   └── deployment/     # 部署 (static_host / disabled)
└── tests/
    ├── contract/       # 212+ Python 契约测试
    └── acceptance/     # 端到端验收测试
```

## 数据流

### 消息发送 → Agent 回复

```
用户输入
  → POST /api/conversations/:id/messages
  → conversations/routes.py 创建消息
  → 如果有 @mention 或 selected_agent: 直接调用指定 Agent
  → 如果 turn_route=true: Turn Router 决策
     → direct_response: 调用 model agent
     → plan_task: Orchestrator 创建 plan → steps → agent runs
     → needs_clarification: 返回澄清消息
  → agent_runs/service.py: build_context_bundle → invoke adapter
  → adapter 返回事件流: assistant_message_completed, run_succeeded/failed
  → 如果成功: 创建 assistant message (含 artifact_references)
  → 如果有 expected_artifacts: 创建 artifact
  → 如果有同标题历史 artifact: 自动生成 diff artifact
  → 返回消息 payload (含 artifact_cards, diff_cards)
```

### Context 构建

```
build_context_bundle(conversation_id)
  → 查询最近 N 条消息 (recent_messages)
  → 查询所有 pinned context 并 resolve (message/artifact/artifact_version/text_note)
  → 查询会话关联 artifacts (artifact_refs)
  → 文本预算控制 + 敏感信息脱敏
  → 返回 { recent_messages, pinned_context, artifact_refs, context_summary }
```

### Adapter 调用

```
custom_openai:
  → 构建 system message (含 pinned context + artifact refs + recent messages)
  → 构建 user message (instruction)
  → POST api_base/chat/completions
  → 返回 assistant_message_completed (含 context_used)

codex_cli / claude_code_cli:
  → 将 context bundle 文本拼接到 instruction 前面
  → 执行 CLI 命令 (codex exec / claude --print)
  → 解析 JSONL/stream-json 输出
  → 返回事件流
```

## 前端卡片系统

消息通过 `collectMessageCards()` 收集以下卡片类型:

- **artifact_card**: 制品卡片，点击预览内容，可下载、可置顶
- **diff_card**: 差异卡片，显示 +/- 行数，点击预览 unified diff
- **patch_card**: 补丁卡片 (review workflow)
- **review_card**: 审核卡片 (review workflow)
- **deployment_card**: 部署状态卡片
- **error_card**: 错误卡片 (来自 send_failure 或 agent_run.failed)

事件系统额外渲染:
- **task_card**: 任务卡片
- **blocked_card**: 阻塞卡片
- **running_card**: Agent 运行中卡片
- **success_card**: Agent 成功卡片
- **failed_card**: Agent 失败卡片 (含 error_code, recovery_hint)

## 数据库

SQLite，表包括:
- `conversations`, `messages`, `conversation_members`
- `agents`
- `agent_runs`, `agent_run_events`
- `artifacts`, `artifact_versions`, `artifact_diffs`, `artifact_patches`
- `tasks`, `plans`, `plan_steps`
- `conversation_events`
- `pinned_context`
- `deployment_releases`, `patch_review_requests`

## 环境变量

| 变量 | 用途 |
|------|------|
| `AGENTHUB_MODEL_API_BASE` | custom_openai API endpoint |
| `AGENTHUB_MODEL_API_KEY` | custom_openai API key |
| `AGENTHUB_MODEL_NAME` | 模型名称 |
| `AGENTHUB_CODEX_EXECUTABLE` | Codex CLI 可执行文件路径 |
| `AGENTHUB_CLAUDE_CODE_EXECUTABLE` | Claude Code CLI 路径 |
| `AGENTHUB_CLAUDE_CODE_REAL_CLI` | 设为 "1" 启用 Claude Code 真实调用 |
| `AGENTHUB_TURN_ROUTER_BACKEND` | Turn router 后端类型 |
