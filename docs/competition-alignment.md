# Competition Alignment Matrix

## 比赛要求对照表

| 比赛要求 | 当前实现状态 | 代码入口 | Demo 入口 | 风险或限制 |
|---------|------------|---------|----------|-----------|
| IM 聊天界面 | done | `apps/web/app.js`, `apps/web/index.html` | 浏览器访问 `localhost:3000` | 无 |
| 对话列表 | done | `apps/web/app.js:renderConversationListHTML` | 左侧面板 | 已修复选中不重排 |
| 单聊 | done | `services/api/app/conversations/routes.py` | 新建 Worker 私聊 | 无 |
| 群聊 | done | `services/api/app/conversations/routes.py` | 新建 Project 群聊 | 无 |
| @Agent | done | `apps/web/app.js:mountArtifactWorkbench` (mention toggle) | 底部输入区 @代理 按钮 | 需要 agent 已配置 |
| Orchestrator 分派 | done | `services/api/app/orchestration/planner.py`, `capability_matcher.py` | 群聊中发送含规划关键词的消息 | 需要 turn router 配置或触发关键词 |
| 至少两个 Agent 接入 | partial | `services/api/app/agents/adapters/` | 代理列表面板 | Codex/Claude CLI 需本地安装；custom_openai 需 API key |
| 上下文记忆 | done | `services/api/app/memory/context_builder.py` | 右侧 Context 面板 | 无 |
| Pin 长期上下文 | done | `services/api/app/memory/pinned_context.py`, `apps/web/app.js:renderPinHTML` | 消息置顶按钮 + Context 面板点击定位 | 无 |
| Artifact 卡片 | done | `services/api/app/artifacts/repository.py:artifact_cards_for_references` | Agent 运行成功后聊天流 | 需要 expected_artifacts 触发 |
| Diff 视图 | done | `services/api/app/artifacts/diff_service.py`, `apps/web/app.js:renderDiffCardHTML` | 点击 diff_card 打开预览 | 仅支持 text 类型 artifact diff |
| 一键应用 Diff | partial | `services/api/app/artifacts/patch_service.py`, `apps/web/app.js:renderDiffCardHTML` | diff_card 上的应用按钮 | 当前按钮 disabled，显示 "应用需通过审核流程" |
| 部署状态卡片 | partial | `services/api/app/deployment/providers/static_host.py` | deployment_card | 需要配置部署目标 |
| 用户自建 Agent | partial | `services/api/app/agents/repository.py` | API POST /api/agents | Web 前端暂无自建 UI，需通过 API |
| AI 协作记录 | done | `docs/ai-collaboration-log.md`, git log | 文档 | 无 |
| 可运行 Demo | done | `docs/local-demo-runbook.md` | 启动后端+前端 | 需要 Python 3.10+ 和 Node 18+ |

## Agent 状态说明

| Agent | 当前状态 | 说明 |
|-------|---------|------|
| custom_openai (Demo Model) | 取决于环境变量 | 需要设置 `AGENTHUB_MODEL_API_BASE` 和 `AGENTHUB_MODEL_API_KEY` |
| Codex CLI | 取决于本地安装 | 需要 `codex` 命令可执行且已认证 |
| Claude Code CLI | 取决于本地安装 | 需要 `claude` 命令可执行且已认证，默认禁用真实调用 |

## 关键修复记录

1. **ContextBundle 注入 Adapter**: 所有 adapter (custom_openai, codex_cli, claude_code_cli) 现在将 pinned context、recent messages、artifact refs 编入模型输入
2. **会话列表不重排**: 移除 "当前会话" 分组，选中态仅通过 CSS class 表达
3. **Pin 点击定位**: Context 面板中的 pin 可点击滚动到对应消息或打开 artifact 预览
4. **Diff 自动生成**: AgentRun 产出 artifact 后自动检测同标题历史版本并生成 diff
5. **Error 表达**: Agent 不可用时返回明确 error_code 和 recovery_hint，不伪造成功
