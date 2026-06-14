# Execution Event Protocol

Scope: A7-0 design precondition only. This document freezes the AgentRun event
schema needed by Adapter contract tests. It does not implement durable SSE
recovery, workers, artifact events, diff events, deployment events, or task trace
projection.

## AgentRunEvent Schema

Minimum persistent event model:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Stable event ID. |
| `run_id` | string | yes | Parent `AgentRun.id`. |
| `conversation_id` | string | yes | Must match the parent run. |
| `sequence` | integer | yes | Monotonic per run, starting at 1. |
| `type` | enum | yes | Event type. |
| `payload_json` | object | yes | Type-specific normalized payload. |
| `created_at` | timestamp | yes | Durable creation timestamp. |

Recommended constraint:

```text
unique(run_id, sequence)
```

A12 may later add conversation-level SSE cursor semantics. A7-0 only requires
per-run sequence ordering.

## Event Types

Minimum A7 event types:

| Type | Terminal | Meaning |
| --- | --- | --- |
| `run_created` | no | Run record was created. |
| `run_started` | no | Adapter invocation started. |
| `adapter_error` | no | Adapter boundary failed before or during provider work. |
| `provider_not_configured` | no | Target agent/provider is not configured for real execution. |
| `assistant_message_delta` | no | Real adapter emitted partial assistant text. |
| `assistant_message_completed` | no | Real adapter completed assistant text. |
| `run_failed` | yes | Run ended in failure. |
| `run_succeeded` | yes | Run ended successfully after a real adapter/provider result. |

Reserved event type:

```text
run_cancelled
```

`run_cancelled` may be added by A7-1 or later if cancellation requires durable
events. A7-0 only freezes `status=cancelled` in the model and `cancel(run_id)` in
the Adapter interface.

A7-3 real direct-response adapters also allow these normalized event types:

| Type | Terminal | Meaning |
| --- | --- | --- |
| `adapter_preflight_started` | no | Adapter-specific readiness checks started inside the invoke boundary. |
| `adapter_preflight_succeeded` | no | Adapter preflight passed without enabling extra tools. |
| `adapter_preflight_failed` | no | Adapter preflight failed before backend work. |
| `adapter_process_started` | no | CLI subprocess or provider request was started. |
| `backend_session_started` | no | Backend session/thread/init event was observed. |
| `backend_retry` | no | Backend reported retry or reconnect behavior. |
| `stdout_line` | no | Raw CLI stdout line was captured. |
| `stderr_line` | no | Raw CLI stderr line was captured. |
| `raw_backend_event` | no | Unknown or unparsed backend JSON was preserved. |
| `usage_reported` | no | Provider usage metadata was reported. |
| `run_timed_out` | yes | Adapter process exceeded AgentHub timeout. A `run_failed` event may follow to keep run status semantics explicit. |

## Common Payload Fields

Every error payload should include:

```text
error_code: string
message: string
provider: string | null
target_agent_id: string | null
recovery_hint: string | null
```

Every assistant payload should include:

```text
message_role: assistant
content_text: string
```

Delta events may include only the new text fragment plus accumulated text if the
adapter can provide it. Completed events must include the final assistant text.

## Required Sequences

Created run:

```text
1 run_created
```

Configured real success:

```text
1 run_created
2 run_started
3..n assistant_message_delta
n+1 assistant_message_completed
n+2 run_succeeded
```

A7-3 CLI success may include preflight, process, raw line, backend session, and
usage events between `run_started` and `assistant_message_completed`, but it
must still finish with `assistant_message_completed` before `run_succeeded` for
`direct_response`.

Provider not configured:

```text
1 run_created
2 run_started
3 provider_not_configured
4 run_failed
```

Adapter error:

```text
1 run_created
2 run_started
3 adapter_error
4 run_failed
```

Adapter timeout:

```text
1 run_created
2 run_started
3..n adapter_preflight_started / adapter_process_started / backend_retry / raw line events
n+1 run_timed_out
n+2 run_failed
```

Rules:

- `run_started` must precede adapter/provider outcome events.
- `run_failed` and `run_succeeded` are terminal for A7.
- `provider_not_configured` must be followed by `run_failed`.
- `provider_not_configured` must never be followed by `run_succeeded`.
- `assistant_message_completed` must be based on a real Adapter result.
- `assistant_message_delta` must not be generated from static fallback text.

## Direct Response Message Write

For `run_mode=direct_response`, the assistant chat message is written only after
all of the following are true:

```text
assistant_message_completed exists
run_succeeded exists
AgentRun.status=succeeded
```

If a run fails after deltas but before completion, A7-0 does not persist a final
assistant message. Future streaming UI may show transient deltas, but that is
not an A7-0 persistence guarantee.

## A7-3.1 Multi-Provider Direct Response Events

For multi-provider `custom_openai` direct responses, the success sequence remains
the normalized A7 sequence:

```text
run_created
run_started
adapter_preflight_started
adapter_preflight_succeeded
assistant_message_completed
usage_reported (optional)
run_succeeded
```

The provider key and model may appear in normalized event payloads. API keys,
authorization headers, raw credential values, provider-specific request bodies,
and provider fallback decisions must not appear in event payloads, assistant
messages, or run responses.

Failure sequences for missing credentials, invalid credentials, network errors,
rate limits, invalid responses, and timeouts must end in `run_failed` and must
not persist an assistant message.

## Provider Not Configured Payload

Required payload shape:

```json
{
  "error_code": "provider_not_configured",
  "message": "Agent provider is not configured for execution.",
  "provider": null,
  "target_agent_id": "<agent_id>",
  "recovery_hint": "Configure provider credentials and model routing for this agent before starting a real run."
}
```

If the provider is known but credentials are missing, `provider` should contain
the provider ID. If no provider can be resolved, it remains null.

## No Fake Success

Forbidden event patterns:

```text
provider_not_configured -> run_succeeded
adapter_error -> run_succeeded
assistant_message_completed from static fallback text
run_succeeded without assistant_message_completed for direct_response
```

Test-only success events are allowed only in tests explicitly named
`adapter_success_contract` and do not count as real Adapter acceptance.

## Out Of Scope

A7-0 does not define:

- Artifact events.
- Diff events.
- Deployment events.
- Worker heartbeat events.
- Durable SSE reconnect cursors.
- Multi-step execution replay.
- A24 trace projection beyond linking run and event IDs.
