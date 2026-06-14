# Execution Trace

Scope: Core-Execution-Trace persistence and replay foundation.

This phase adds durable conversation-level events and task trace summaries. It
does not implement true SSE streaming, deploy new providers, workspace writes,
Lark integration, MCP integration, or self-created agents.

## Event Schema

`conversation_events` is persisted in SQLite and exposed through
`GET /api/conversations/{id}/events`.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Stable event ID. |
| `conversation_id` | string | Parent conversation. |
| `task_id` | string or null | Present for task/plan/step scoped events. |
| `plan_id` | string or null | Present for plan/step scoped events. |
| `step_id` | string or null | Present for step/run scoped planned-step events. |
| `run_id` | string or null | Present for AgentRun lifecycle events. |
| `artifact_id` | string or null | Present for artifact/diff/review/patch events. |
| `deployment_id` | string or null | Present for deployment release events. |
| `sequence` | integer | Monotonic per conversation, starting at 1. |
| `type` | string | One of the supported event types below. |
| `payload_json` | object | Type-specific payload, decoded in API responses. |
| `created_at` | timestamp | Durable creation timestamp. |

The API also includes a `payload` alias for existing callers, but
`payload_json` is the canonical field for this phase.

## Sequence Rule

Sequence is assigned from a persistent per-conversation cursor table in the same
SQLite transaction as the event insert. It is monotonic within a conversation
and independent across conversations.

`GET /api/conversations/{id}/events?after_sequence=N` returns only events with
`sequence > N`.

## API Behavior

`GET /api/conversations/{id}/events`

- Returns persisted events ordered by `sequence ASC`.
- Supports `after_sequence`.
- Also supports scoped filters: `task_id`, `run_id`, `artifact_id`,
  `deployment_id`, and `limit`.
- Returns an empty list when no events exist.
- Does not synthesize events from memory.

`GET /api/tasks/{id}`

- Returns the existing task, plan, and steps.
- Adds `runs`, `events`, and `event_summary`.
- `runs` contains AgentRuns linked through the task's plan steps.
- `events` contains the source message/planner events plus events scoped to
  the task.
- `event_summary` contains `count`, `last_sequence`, and per-type counts.

## Supported Event Types

- `message.created`
- `planner.decision_created`
- `task.created`
- `plan.created`
- `step.created`
- `step.blocked`
- `agent_run.created`
- `agent_run.started`
- `agent_run.succeeded`
- `agent_run.failed`
- `artifact.created`
- `artifact.version_created`
- `diff.created`
- `review_request.created`
- `patch_application.applied`
- `patch_application.failed`
- `patch_application.conflict`
- `deployment_release.created`
- `deployment_release.published`
- `deployment_release.failed`

## Source Rules

Events are written only after the corresponding durable record or state change
has succeeded. In particular, `agent_run.succeeded` is written only after the
run status has been updated to `succeeded`, and `agent_run.failed` is written
only after the run status has been updated to `failed`.

No fake event source is used. Refresh recovery is a replay of persisted
`conversation_events`, not process memory.

## Web Timeline

The Web workbench reloads `GET /api/conversations/{id}/events` when a
conversation is refreshed. Timeline rows are ordered by sequence and show event
type, persisted status payload when present, created timestamp, and linked
task/step/run/artifact/deployment IDs.

The timeline does not infer terminal states from messages or local state.
