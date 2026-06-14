# Dispatch Contract

Scope: A5 frozen behavior, A6 planning dispatch, and A6.5 Turn Routing
compatibility. This contract defines dispatch metadata only; it does not
authorize AgentRun or Adapter execution.

## Mention Dispatch Frozen Contract

A5 mention dispatch is frozen as:

- Source message has persisted `mentions`.
- Each mention contains an `agent_id`.
- The mentioned agent must exist and have `enabled=true`.
- Dispatch must create a persisted `task`, `plan`, and one or more `plan_steps`.
- Each mention-dispatched step must set:
  - `assigned_agent_id` to the mentioned `agent_id`
  - `dispatch_source` to `mention`
  - `dispatch_reason` to a stable explanation containing `explicit_mention`

Mention dispatch must never silently choose another agent.

## Dispatch Source Enum

Current allowed values:

- `mention`
- `capability`
- `blocked`

No other value is allowed without updating this contract and tests.

## A5 Forbidden Runtime Effects

A5 does not allow:

- `AgentRun`
- Adapter invocation
- `run_succeeded`
- Artifact creation
- Diff creation
- Deployment creation
- fake success
- fallback to a default agent

`profile_only` agents may be assigned to a `plan_step.assigned_agent_id`, but they must not be presented as executable adapters.

## Mention Error Contract

Unknown agent:

```json
{
  "error": "unknown_agent",
  "message": "Mentioned agent does not exist.",
  "agent_id": "..."
}
```

Disabled agent:

```json
{
  "error": "agent_disabled",
  "message": "Mentioned agent is disabled.",
  "agent_id": "..."
}
```

Both errors must stop task/plan creation for that message. They must not fallback to another agent and must not turn into `provider_not_configured` success.

## A6 Dispatch Contract

For non-mentioned task-like messages, A6 may add:

- `dispatch_source="capability"` when an enabled agent profile matches the step capability.
- `dispatch_source="blocked"` when no enabled agent profile can be assigned.

Status semantics for successful A6 planning:

- `task.status="planned"`
- `plan.status="ready"`
- `plan_step.status="assigned"` when `assigned_agent_id` is present
- `plan_step.status="blocked"` when `blocked_reason` is present

A6 blocked is step-level only. It must not set `task.status` or `plan.status` to `blocked`.

Capability matching reads only `enabled=true` AgentProfile records and uses this frozen mapping after exact `step.kind` tag matches:

| step.kind | capability_tags considered after exact kind match |
| --- | --- |
| `analysis` | `analysis`, `research`, `planning`, `document` |
| `implementation` | `implementation`, `code`, `frontend`, `backend` |
| `review` | `review`, `test`, `qa`, `security` |

When multiple profiles match, A6 must choose deterministically by ascending `agent.id`. When none match, it must set:

- `dispatch_source="blocked"`
- `blocked_reason="no_capability_match"`

A6 must not fallback to a default agent. `profile_only` agents may be assigned for planning, but no run may start and dispatch reason must state that.

Capability dispatch reason format:

```text
capability:<agent_id>: matched step kind <kind> using capability tags <matched_tags>; execution_enabled=<bool>; configured=<bool>; health_status=<status>; profile_only=<bool>; no_run_start=true
```

Blocked dispatch reason format:

```text
blocked:no_capability_match: no enabled agent profile matched step kind <kind> using capability tags <candidate_tags>
```

## Router Error Contract

For messages routed into A6 planning, an unconfigured turn router returns an
explicit error and creates no `task`, `plan`, or `plan_step`:

```json
{
  "error": "turn_router_not_configured",
  "code": "turn_router_not_configured",
  "error_code": "turn_router_not_configured",
  "message": "Turn router backend is not configured.",
  "recovery_hint": "Configure a real turn router backend or enable the test turn router backend only in tests."
}
```

Invalid TurnDecision output returns `turn_router_invalid_output` and creates no
`task`, `plan`, or `plan_step`. The Orchestrator must not recover by running a
keyword classifier or selecting a default agent.

## Turn Routing Compatibility

TurnDecision is the future top-level decision for chat turns:

```text
no_action | direct_response | plan_task | needs_clarification
```

Current A5:

- During A6.5, explicit `@Agent` messages bypass TurnRouter.
- They remain A5 mention dispatch and create task/plan/step.
- This maps conceptually to `plan_task` with `target_agent_ids` containing the
  mentioned agent.
- This is a transitional compatibility rule to preserve A5 acceptance before
  AgentRun/Adapter exists.
- This is not the final product behavior.
- Future `@Agent + simple question -> direct_response` requires A5.5/A7 tests
  and must not silently alter current A5 acceptance.

Final product target after A7:

- `@Agent + simple question` goes through TurnRouter and becomes
  `direct_response`.
- `@Agent + complex task` goes through TurnRouter and becomes `plan_task`.
- TurnRouter reads persisted mentions to produce the TurnDecision target.
- `direct_response` creates
  `AgentRun(source_type="message", run_mode="direct_response")`.
- `direct_response` must not create task/plan/step or a fake assistant answer.

Current A6:

- Non-mentioned task planning maps to `plan_task`.
- Historical task planning has been migrated to `TurnDecision(plan_task)`.
- Historical non-task planning has been split into either `no_action` or
  `direct_response`.

Router backend boundary:

- Product path uses a real router backend for structured decisions.
- Test backends are test-only and must not become product defaults.
- If a conversation expects an agent or Orchestrator response and router is not
  configured, return `turn_router_not_configured`.
- No keyword routing, default-agent fallback, fake assistant answer, or fake
  success is allowed.
- Do not treat the current A5 bypass as final product logic.
- Do not fake `@Agent + simple question` direct responses during A6.5.
- Do not break current A5 acceptance during migration.
