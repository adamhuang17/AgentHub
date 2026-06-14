# AgentHub Competition

AgentHub Competition 是一个以 IM 群聊为核心体验的多 Agent 协作平台。用户在 `/agenthub` 中选择或 @ 不同 Agent，让 Orchestrator、Codex、Claude、AgentHub Coding Agent 和自定义模型 Agent 平级协作，生成代码、文档、演示稿、Diff、预览和部署产物。

## 项目定位

- Web 前端：AgentHub 对话台，入口在 `apps/web/packages/app/src/pages/agenthub.tsx`。
- Control Plane：Python API，负责 Agent、Conversation、Orchestrator、AgentRun、Artifact、Preview、Deploy。
- Agent Runtime：通过 adapter 接入 Codex CLI、Claude Code CLI、自定义 OpenAI-compatible 模型，以及 AgentHub 本地编码运行时。
- 产物闭环：群聊请求 -> AgentRun -> Artifact / Diff / Preview -> Download / Static Deploy。

> 说明：仓库仍保留若干 `@opencode-ai/*` workspace 包名，这是底层运行时依赖和历史包名，不再作为用户体验中的产品主语。面向用户的入口统一叫 AgentHub。

## 目录结构

```text
AgentHub/
  apps/web/                  # AgentHub Web workspace
  services/api/              # AgentHub Python Control Plane
  config/                    # 环境配置示例
  docs/                      # 架构、验收、演示和 no-fake-success 文档
  integration/               # 来源边界说明
  scripts/                   # 本地启动与检查脚本
  var/                       # 本地运行数据与测试产物
```

## 运行前要求

- Python 3.11+
- Bun 1.3+
- 可选：Codex CLI / Claude Code CLI
- 可选：OpenAI-compatible API Key
- 可选：AgentHub 本地编码运行时所需模型凭据

缺少 Bun、API Key、CLI 或本地编码运行时时，系统必须显示明确错误码，例如 `bun_not_installed`、`opencode_server_unavailable`、`turn_router_not_configured`、`missing_credentials`，不得伪造成功。

## 快速启动（三个终端）

```powershell
# 终端 1：初始化环境（首次运行）
cd D:\path\to\AgentHub
Copy-Item .env.example .env
.\scripts\check-layout.ps1

# 终端 1：启动 Python API
.\scripts\dev-api.ps1

# 终端 2：启动 OpenCode 编码运行时
.\scripts\dev-agent-runtime.ps1

# 终端 3：启动 Web 前端
.\scripts\dev-web.ps1
```

打开浏览器访问：`http://127.0.0.1:3000/agenthub`

> **注意**：三个服务（API、编码运行时、Web）必须在各自独立的终端中运行。编码运行时启动后会监听 `http://127.0.0.1:4096`，如果端口已被占用会报 `ServeError`，此时无需重复启动。

## 当前能力

- 多 Agent @：单 Agent 直接执行，多 Agent 在 Web 群聊中按 @ 顺序生成顺序计划；配置了 Router 时优先使用 Router 的语义计划。
- Markdown 渲染：对话消息和文档预览使用结构化 Markdown 样式，Diff fence 会显示为增删行块。
- Diff 产物：支持 `source_diff` / `diff_preview` artifact，并在右侧产物面板结构化展示文件、hunk、行号、增删统计。
- Office 产物：当用户请求 Word/PPT 时，成功的 Agent 输出会生成可下载 `.docx` / `.pptx` artifact，并提供只读预览摘要。
- 产物交付：artifact 支持详情、预览、下载；Web 预览产物可继续发布到静态部署 provider。

## 演示流程

1. 打开 `/agenthub`。
2. 新建群聊或选择已有会话。
3. 发送 `@Codex @Claude 帮我实现并评审这个需求`，观察顺序计划和 AgentRun。
4. 发送 `@千问 你能生成一个 Word 文档吗`，完成后在右侧产物面板下载 `.docx`。
5. 发送包含 diff fence 的消息，确认对话区显示结构化 Diff。
6. 选择 Web artifact 后点击发布，成功后返回真实 `/static-deployments/...` URL。

## No Fake Success

本项目禁止：

- 未调用真实 Agent 却显示 Agent succeeded。
- 未生成真实 Artifact 却显示 ArtifactCard。
- 未生成真实 Diff 却显示 DiffCard。
- 未复制/发布真实文件却显示 Deployment published。
- 未配置 provider 时 fallback 到 mock provider。
- 写死 Agent 回复、Artifact、Diff 或部署 URL 作为真实结果。

详见 `docs/no-fake-success-policy.md`。
