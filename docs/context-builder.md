# Context Builder

Pre-Lark-Local-Product-Demo adds durable pinned context and a bounded
`ContextBundle` for local IM, TurnRouter input, and AgentRun requests.

## pinned_context

`pinned_context` is stored as references, not copied source bodies:

| Column | Meaning |
| --- | --- |
| `id` | Stable pin id. |
| `conversation_id` | Owning conversation. |
| `source_type` | `message`, `artifact`, `artifact_version`, or `text_note`. |
| `source_id` | Source record id, nullable only for `text_note`. |
| `note` | Optional user note; required for `text_note`. |
| `created_at` | UTC creation timestamp. |

Pin validation is conversation-scoped. Message pins must point at a message in
the same conversation. Artifact and ArtifactVersion pins must point at records
owned by the same conversation. Invalid and cross-conversation sources fail.

## ContextBundle

`GET /api/conversations/{id}/context` returns:

```json
{
  "conversation_id": "conv_...",
  "recent_messages": [],
  "pinned_context": [],
  "artifact_refs": [],
  "conversation_summary": null,
  "selected_ranges": [],
  "constraints": {
    "max_recent_messages": 20,
    "max_message_chars": 4000,
    "max_total_chars": 16000
  },
  "context_summary": {
    "recent_message_count": 0,
    "pinned_count": 0,
    "artifact_ref_count": 0,
    "truncated": false
  }
}
```

Defaults can be tuned with:

- `AGENTHUB_CONTEXT_RECENT_MESSAGES`
- `AGENTHUB_CONTEXT_MAX_MESSAGE_CHARS`
- `AGENTHUB_CONTEXT_MAX_TOTAL_CHARS`

Message text is bounded per message and across the bundle. Secret-like material
is redacted before it enters the bundle. Binary artifacts are represented by
metadata only. Artifact refs include id, current version id, type, title,
status, checksum, and MIME type.

Successful context builds write `context.built`. Failed builds write
`context.build_failed` when a conversation-scoped event can be recorded.

## AgentRun Use

`direct_response` and `planned_step` AgentRun creation now build a fresh
ContextBundle before creating the run. Adapter requests receive that bounded
bundle. AgentRun records do not persist full context. Run events store only
`context_summary` and `context_ref`.

