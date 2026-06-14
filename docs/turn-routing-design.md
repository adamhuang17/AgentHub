# Turn Routing Design

Scope: A6.5 / A7-0 design only. This document freezes turn-routing semantics
before AgentRun and Adapter implementation. It does not authorize business-code
changes, tests, artifact creation, diff creation, deployment, or fake responses.

## Goal

AgentHub must route each persisted user turn according to structured conversation
context and a structured router decision:

```text
user message
  -> persist message
  -> TurnRouterGateway
  -> TurnDecision schema validation
  -> no_action: message only
  -> direct_response: direct AgentRun in A7
  -> plan_task: task / plan / plan_steps
  -> needs_clarification: clarification response path
```

Product code must not use keyword lists, local natural-language if-else
classifiers, or test-text hardcoding to decide between these paths.

## Conversation Modes

Initial conversation modes:

| Mode | Meaning | Default target source |
| --- | --- | --- |
| `private_agent` | User is speaking to one concrete agent. | The private agent from conversation membership. |
| `private_orchestrator` | User is speaking to the Orchestrator. | Orchestrator. |
| `group` | User, Orchestrator, and one or more agents are in one chat. | Mentions first; otherwise group auto-orchestration policy. |

The mode is structured metadata. It must not be inferred from message text.

## Mention Cases

Initial mention cases:

| Case | Source | Routing meaning |
| --- | --- | --- |
| Explicit mention | Persisted `message.mentions[]` metadata. | The mentioned agent or Orchestrator is the explicit target. |
| No mention | Empty persisted `message.mentions[]`. | The router uses conversation mode and structured policy such as `auto_orchestrate`. |

The router must not guess agent names from natural language.

### A5 Transitional Compatibility

In the current A6.5 stage, messages with non-empty `mentions` bypass
TurnRouter and continue through A5 mention dispatch.

This is a transitional compatibility rule:

- It preserves the already accepted A5 behavior while AgentRun and Adapter are
  not implemented.
- It keeps `@Agent` dispatch on the current durable task/plan/step path.
- It prevents A6.5 from faking `direct_response` before A7 exists.
- It is not the final product routing behavior.

This bypass must not be treated as a permanent product rule.

## TurnDecision Schema

Minimum schema:

```text
decision_type: no_action | direct_response | plan_task | needs_clarification
target_agent_ids: list[string]
goal: string | null
steps: list[TurnPlanStep]
reason: string
confidence: low | medium | high
```

Recommended additional fields:

```text
target_type: none | agent | orchestrator
target_source: private_chat | mention | auto_orchestrate | none
clarification_question: string | null
```

`TurnPlanStep`:

```text
kind: analysis | implementation | review
objective: string
required_capabilities: list[string]
depends_on: list[string]
expected_output: object
```

Shape rules:

| decision_type | Required shape | Forbidden shape |
| --- | --- | --- |
| `no_action` | `target_agent_ids=[]`, `goal=null`, `steps=[]` | Assistant answer, task, AgentRun. |
| `direct_response` | One or more concrete targets, `goal=null`, `steps=[]` | `answer`, task, plan, plan step. |
| `plan_task` | `goal` is non-empty, `steps` length is 1-3 | `deploy`, `artifact`, `diff`, `run`, `adapter`, `agent_run` step kinds. |
| `needs_clarification` | `steps=[]`, structured clarification question recommended | task, plan, plan step. |

Step dependency rules reuse A6 implicit keys:

```text
step-1, step-2, step-3
```

A step may depend only on earlier step keys.

`direct_response` deliberately has no `answer` field. The router chooses the
path and target; an AgentRun and Adapter produce the answer later.

## Routing Matrix

| Scenario | Mention case | Expected TurnDecision | Target | Product action |
| --- | --- | --- | --- | --- |
| Private Agent + simple question | No mention | `direct_response` | Current private agent. | A7 creates `AgentRun(source_type=message, run_mode=direct_response)` and assistant message. No task. |
| Private Agent + complex task | No mention | `plan_task` | Current private agent, or Orchestrator if backend chooses escalation. | Create task/plan/steps. Steps may initially target the private agent when structurally valid. |
| Private Orchestrator + simple question | No mention | `direct_response` | Orchestrator response agent/runtime. | A7 creates direct AgentRun. No task. |
| Private Orchestrator + complex task | No mention | `plan_task` | Orchestrator. | Create task/plan/steps and dispatch by capability. |
| Group + `@Agent` + simple question | Explicit mention | Future `direct_response`; current A5 compatibility bypasses TurnRouter and remains A5 mention dispatch. | Mentioned agent. | A7 direct response after A5.5/A7 matrix update; current A5 acceptance still creates task/plan/step. |
| Group + `@Agent` + complex task | Explicit mention | `plan_task` | Mentioned agent. | Create task/plan/step; current A5 maps here. |
| Group + no `@` + simple small talk | No mention | `no_action` | None. | Persist message only. |
| Group + no `@` + simple knowledge question | No mention | `direct_response` when `group_auto_orchestrate=true`; otherwise may be `no_action`. | Orchestrator response target. | A7 direct response, no task. |
| Group + no `@` + complex task | No mention | `plan_task` | Orchestrator. | Create task/plan/steps and dispatch by capability. Current A6 maps here. |

`group_auto_orchestrate=true` is the competition-friendly default. Enterprise IM
deployments may configure it false, but the decision still comes from a real
TurnRouter backend using structured context, not local keywords.

## Router And Planner Backend Boundary

Product path:

- A real TurnRouter backend returns a validated TurnDecision.
- A real Planner backend may still be used behind `plan_task` to generate steps,
  but the top-level turn decision is TurnDecision.
- Test router/planner backends are enabled only in test environments.
- Test backends consume injected structured decisions; they do not synthesize
  decisions from message text.
- If a conversation expects an agent or Orchestrator response and the router is
  not configured, return `router_not_configured`.
- If `plan_task` needs a planner and that planner is not configured, return
  `planner_not_configured`.
- Never fallback to keyword rules, default agents, fake adapters, or static
  success responses.

Disabled router error shape:

```json
{
  "error": "router_not_configured",
  "code": "router_not_configured",
  "error_code": "router_not_configured",
  "message": "Turn router backend is not configured.",
  "recovery_hint": "Configure a real turn router backend or enable the test backend only in tests."
}
```

## `orchestrate=true`

`orchestrate=true` is only a testing, debugging, or advanced hint. It may be used
to force a route into the Orchestrator during controlled validation, but it is
not the final product's main entry.

Default product behavior is decided by TurnRouter using persisted message data,
conversation mode, mentions, available agents, policy fields, pinned context,
and recent messages.

## A5 / A6 Compatibility

A5 current behavior:

- In A6.5, explicit `@Agent` messages bypass TurnRouter.
- A5 mention dispatch creates task/plan/step.
- Conceptually this maps to `TurnDecision(decision_type="plan_task",
  target_agent_ids=[mentioned_agent_id])` for the current frozen acceptance.
- This preserves A5 acceptance before AgentRun/Adapter exists.
- This is not final product behavior.
- Future `@Agent + simple question -> direct_response` requires a new A5.5/A7
  acceptance update and must not silently change current A5 tests.

A6 current behavior:

- Non-mentioned planned work maps to `TurnDecision(decision_type="plan_task")`.
- Historical task routing maps to `plan_task`.
- Historical non-task routing has been split into `no_action` or
  `direct_response`; it must not keep carrying both meanings.
- Clarification routing maps to TurnDecision `needs_clarification`.

Migration path:

1. Keep A5/A6 acceptance stable while this design is introduced.
2. Add TurnDecision schema and router contract tests.
3. Route A6 `plan_task` through TurnDecision while preserving task/plan/step
   persistence semantics.
4. Move simple answer behavior into A7 direct AgentRun.
5. Retire the old top-level planning decision once TurnDecision covers
   `no_action`, `direct_response`, `plan_task`, and `needs_clarification`.

## Final Product Mention Target

After A7 introduces real AgentRun and Adapter support:

- `@Agent + simple question` should enter TurnRouter and return
  `TurnDecision(decision_type="direct_response")`.
- `@Agent + complex task` should enter TurnRouter and return
  `TurnDecision(decision_type="plan_task")`.
- TurnRouter must read persisted `message.mentions[]` to resolve the target.
- `direct_response` must create
  `AgentRun(source_type="message", run_mode="direct_response")`.
- `direct_response` must not create task/plan/step.
- `direct_response` must not create a fake answer or claim success without a
  real Adapter result.

A6.5 must not implement a fake direct response for mentioned simple questions,
and migration must not break current A5 acceptance.

## A7 AgentRun Source Design

A7 AgentRun must support two source types:

| source_type | Required source id | run_mode | Meaning |
| --- | --- | --- | --- |
| `message` | `source_message_id` | `direct_response` | The run answers a user turn directly. |
| `plan_step` | `source_plan_step_id` | `planned_step` | The run executes one planned step. |

Rules:

- `run_mode="direct_response"` must not create task/plan/step.
- `run_mode="planned_step"` must be linked to an existing plan step.
- Provider/configuration failures surface as explicit failures such as
  `provider_not_configured`, `credential_invalid`, `adapter_not_configured`, or
  `timeout`.
- A7 must not claim `run_succeeded` without a real Adapter result.

## Out Of Scope

A6.5 / A7-0 design does not implement:

- AgentRun execution.
- Adapter invocation.
- Artifact records.
- Diff records.
- Deployment records.
- Keyword routing.
- Test backend as production default.
- User-required manual Plan Mode as the main product flow.
- Treating the current A5 TurnRouter bypass as final product logic.
- Faking `@Agent` direct responses before A7.
