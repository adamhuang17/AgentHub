# Agent Adapter Contract

## AgentProfile

```json
{
  "id": "opencode",
  "name": "OpenCode",
  "provider": "opencode",
  "adapter_kind": "opencode_http",
  "avatar_url": "string | null",
  "capability_tags": ["coding", "frontend", "diff"],
  "enabled": true,
  "configured": true,
  "health_status": "ready | unavailable | not_configured"
}
```

## AgentRunRequest

```json
{
  "run_id": "string",
  "conversation_id": "string",
  "message_id": "string",
  "agent_id": "string",
  "instruction": "string",
  "context_bundle": {},
  "expected_artifacts": ["code_file", "source_diff", "web_preview"]
}
```

## AgentRunEvent

```json
{
  "type": "adapter_preflight_started | adapter_preflight_succeeded | adapter_preflight_failed | adapter_process_started | assistant_message_completed | artifact_created | run_succeeded | run_failed",
  "run_id": "string",
  "agent_id": "string",
  "sequence": 1,
  "payload": {},
  "created_at": "ISO-8601"
}
```

## 错误码

| 错误码 | 触发条件 |
|---|---|
| `provider_not_configured` | provider 没有配置 |
| `missing_credentials` | 缺 API Key 或登录态 |
| `adapter_executable_not_found` | CLI 不存在 |
| `opencode_server_unavailable` | OpenCode HTTP service 不可达 |
| `adapter_timeout` | Adapter 超时 |
| `adapter_failed` | Adapter 真实失败 |

## 禁止

- 不可达时返回成功。
- 没有 assistant message 时伪造回复。
- 没有 diff 时伪造 diff。
- 未配置 provider 时 fallback 到 mock。
