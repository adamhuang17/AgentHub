# AgentRun Design

Scope: A7-0 design precondition only. This document freezes the AgentRun data
model, request schema, event relationship, and routing behavior needed before
A7 implementation. It does not declare A7 passed.

## Acceptance Boundary

Acceptance ID:

```text
A7 design precondition only
```

This stage writes design documents only. It does not change business code,
frontend code, infra, or tests.

## AgentRun Model

Minimum persistent model:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Stable run ID. |
| `conversation_id` | string | yes | Conversation that owns this run. |
| `source_type` | enum | yes | `message` or `plan_step`. |
| `source_message_id` | string/null | conditional | Required when `source_type=message`. Optional trace field for planned runs. |
| `plan_step_id` | string/null | conditional | Required when `source_type=plan_step`; must reference an existing plan step. |
| `target_agent_id` | string | yes | Agent selected by TurnRouter or existing plan step assignment. |
| `run_mode` | enum | yes | `direct_response` or `planned_step`. |
| `status` | enum | yes | `created`, `running`, `failed`, `succeeded`, or `cancelled`. |
| `error_code` | string/null | no | Required for `failed`; null for successful runs. |
| `created_at` | timestamp | yes | Durable creation timestamp. |
| `updated_at` | timestamp | yes | Updated on every status or error change. |

Valid source pairing:

```text
source_type=message:
  run_mode=direct_response
  source_message_id required
  plan_step_id null

source_type=plan_step:
  run_mode=planned_step
  plan_step_id required
  existing plan_step required
```

Invalid pairings are contract failures:

- `source_type=message` with `run_mode=planned_step`.
- `source_type=plan_step` with `run_mode=direct_response`.
- `planned_step` without an existing `plan_step_id`.
- `direct_response` that creates task, plan, or plan step records.

## Status Semantics

Initial status:

```text
created
```

Allowed terminal statuses:

```text
failed
succeeded
cancelled
```

Normal transitions:

```text
created -> running -> succeeded
created -> running -> failed
created -> cancelled
running -> cancelled
```

Rules:

- `failed` requires `error_code`.
- `provider_not_configured` must be represented as `status=failed`.
- `succeeded` requires a real Adapter result.
- `cancelled` is supported by the model, but long-running cancellation
  machinery is not part of A7-0.

## AgentRunRequest Schema

Minimum request schema accepted by every Adapter:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `run_id` | string | yes | Existing `AgentRun.id`. |
| `conversation_id` | string | yes | Must match the run and source. |
| `source_type` | enum | yes | `message` or `plan_step`. |
| `source_message_id` | string/null | conditional | Required for direct responses. |
| `plan_step_id` | string/null | conditional | Required for planned steps. |
| `target_agent_id` | string | yes | Target agent profile. |
| `run_mode` | enum | yes | `direct_response` or `planned_step`. |
| `instruction` | string | yes | Normalized instruction for the target adapter. |
| `context_bundle` | object | yes | Conversation-scoped context. |
| `workspace_ref` | object/null | yes | Opaque workspace locator or null. |
| `allowed_tools` | list[string] | yes | Explicit tool allowlist; may be empty. |
| `expected_artifacts` | list[object] | yes | Future artifact intent; empty in minimal A7. |

Example shape:

```json
{
  "run_id": "run_123",
  "conversation_id": "conv_123",
  "source_type": "message",
  "source_message_id": "msg_123",
  "plan_step_id": null,
  "target_agent_id": "agent_123",
  "run_mode": "direct_response",
  "instruction": "Answer the user's question.",
  "context_bundle": {
    "source_message_id": "msg_123",
    "recent_messages": [],
    "pinned_message_ids": []
  },
  "workspace_ref": null,
  "allowed_tools": [],
  "expected_artifacts": []
}
```

Forbidden request contents:

- Provider API keys.
- Provider-specific request bodies.
- Adapter-specific fields.
- Cross-conversation messages, pins, memory, or task context.
- Fake expected artifacts that imply A8 success.

## AgentRunEvent Relationship

Every run has zero or more durable `AgentRunEvent` records. The event schema and
ordering rules are frozen in `docs/execution-event-protocol.md`.

Required relationship:

```text
agent_runs.id = agent_run_events.run_id
agent_runs.conversation_id = agent_run_events.conversation_id
```

The first persisted event for a created run is `run_created`. Adapter invocation
then emits `run_started` before provider or assistant events.

## Disabled And Not Configured Behavior

Agent profile readiness has at least two separate flags:

```text
enabled=true
configured=false
```

Meaning:

- `enabled=true` means the profile can appear in conversations and may be
  selected by routing or planning.
- `configured=false` means the provider/model/credential path is not ready for
  execution.

When `configured=false`:

```text
create AgentRun -> status created
write run_created
invoke Adapter or disabled adapter boundary
write run_started
write provider_not_configured
set status failed
set error_code provider_not_configured
write run_failed
```

Forbidden:

- Writing `run_succeeded`.
- Writing a fake assistant answer.
- Treating provider-not-configured as a successful adapter response.
- Falling back to another provider or default agent.

## Direct Response Behavior

For `TurnDecision(decision_type="direct_response")`:

```text
source_type=message
run_mode=direct_response
source_message_id=<user message id>
plan_step_id=null
```

Flow:

1. Persist the user message first.
2. Validate TurnDecision target.
3. Create `AgentRun`.
4. Build `AgentRunRequest` from the message and conversation context.
5. Invoke the Adapter.
6. On `assistant_message_completed` plus `run_succeeded`, write the assistant
   message.
7. On `provider_not_configured`, keep the run failed and write no assistant
   answer.

This path must not create `task`, `plan`, or `plan_step` records.

## Planned Step Behavior

For execution of an existing plan step:

```text
source_type=plan_step
run_mode=planned_step
plan_step_id=<existing plan step id>
```

Flow:

1. Validate that the plan step exists.
2. Validate that the plan step belongs to the same conversation.
3. Validate that the target agent matches the existing assignment.
4. Create `AgentRun`.
5. Build `AgentRunRequest` from the plan step objective and context bundle.
6. Invoke the Adapter.
7. On `provider_not_configured`, fail the run with the same error behavior as
   direct response.

This path must not create an isolated run without a plan step. It must not
reroute the original user message or silently choose a default agent.

## Direct Response Vs Planned Step

| Dimension | `direct_response` | `planned_step` |
| --- | --- | --- |
| Source | Persisted user message. | Existing persisted plan step. |
| `source_type` | `message` | `plan_step` |
| Required ID | `source_message_id` | `plan_step_id` |
| Creates task/plan/step | No. | No new task/plan/step; binds existing step. |
| Assistant message | Written only after real Adapter completed answer. | Not defined by A7-0; later execution layers decide task/artifact output. |
| Main failure | Failed run and event, no fake answer. | Failed run and event, step remains traceable. |

## Test Backend Boundary

`TestAdapterBackend` may be added in A7-1 only under test configuration.

Rules:

- It is never the production default.
- It may validate request and event shapes.
- It may emit fake success only for tests explicitly named
  `adapter_success_contract`.
- Fake success does not count as real Adapter acceptance.
- A7 P0 should primarily verify `provider_not_configured` and protocol
  behavior.

## A7-0 Does Not Do

A7-0 does not implement:

- Artifact records.
- Diff records.
- Deployment records.
- Long-running workers.
- SSE recovery.
- Multi-step execution engine.
- True Codex/OpenCode/Claude integration.
- Real provider credential flow.
- Fake assistant answers.

## A7-1 Likely Implementation Files

Likely files to add or modify when implementation begins:

- `services/api/app/agent_runs/schema.py`
- `services/api/app/agent_runs/models.py`
- `services/api/app/agent_runs/repository.py`
- `services/api/app/agent_runs/routes.py`
- `services/api/app/agent_runs/events.py`
- `services/api/app/agent_runs/adapter_gateway.py`
- `services/api/app/agent_runs/adapters/base.py`
- `services/api/app/agent_runs/adapters/disabled.py`
- `services/api/app/agent_runs/adapters/test_backend.py`
- `services/api/app/conversations/routes.py`
- `services/api/app/orchestration/turn_router_gateway.py`
- `services/api/app/shared/database.py`
- `tests/schema/test_agent_run_schema.py`
- `tests/contract/test_agent_adapter_protocol.py`
- `tests/service_contract/test_agent_run_provider_not_configured.py`
- `tests/acceptance/test_a7_agent_adapter_contract.py`

This file list is implementation guidance, not authorization to change those
files during A7-0.

