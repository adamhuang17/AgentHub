# Agent Adapter Protocol

Scope: A7-0 protocol design only. This document freezes the adapter boundary
used by AgentRun. It does not implement adapters, provider calls, artifacts,
diffs, deployments, workers, SSE recovery, or real Codex/OpenCode/Claude
integration.

Related documents:

- `docs/agent-run-design.md`
- `docs/execution-event-protocol.md`
- `docs/turn-routing-design.md`
- `docs/dispatch-contract.md`

## Boundary

The Orchestrator and TurnRouter may create an `AgentRunRequest`, but they must
not contain adapter-specific provider fields, request translations, API keys, or
model-wire details.

Adapter-specific configuration is resolved behind the Adapter boundary from the
target agent profile and provider registry. This follows the separation shown in
the local references:

- Cline runtime keeps run status and events inside the runtime boundary.
- 9Router keeps provider URL, target format, credential, and response
  translation logic behind the provider facade.

## Adapter Interface

Every Adapter must expose the same interface:

```text
health() -> AdapterHealth
invoke(request: AgentRunRequest) -> iterator/list[AgentRunEvent]
cancel(run_id: string) -> AdapterCancelResult
```

`health()` is side-effect free and reports whether this adapter can currently
accept real provider work.

Minimum `AdapterHealth` shape:

```text
provider: string | null
adapter_kind: string
configured: bool
status: ready | not_configured | missing_credentials | unsupported_provider | unavailable
error_code: string | null
recovery_hint: string | null
checked_at: string
capabilities: list[string]
message: string | null
```

`invoke(request)` accepts only the normalized `AgentRunRequest` schema. It emits
normalized `AgentRunEvent` records. A synchronous adapter may return a list; a
streaming adapter may return an iterator. The persistence layer owns durable
storage of runs and events.

`cancel(run_id)` requests cancellation. A7-0 freezes the method shape only; a
durable cancellation worker and recovery semantics are out of scope.

## AgentRun Sources

AgentRun must support both direct chat answers and planned-step execution.

| Field | Values | Meaning |
| --- | --- | --- |
| `source_type` | `message` | The run was created from a user message for a direct response. |
| `source_type` | `plan_step` | The run was created to execute a persisted plan step. |
| `run_mode` | `direct_response` | The run should produce an assistant answer for the source message. |
| `run_mode` | `planned_step` | The run should execute the source plan step. |

Required pairing:

```text
source_type=message   -> run_mode=direct_response -> source_message_id required, plan_step_id null
source_type=plan_step -> run_mode=planned_step    -> plan_step_id required, existing plan_step
```

Invalid pairings must be rejected by schema or contract tests. `plan_step_id`
is the canonical field name for planned-step runs.

## AgentRunRequest

All adapters accept this same request shape:

```text
run_id: string
conversation_id: string
source_type: message | plan_step
source_message_id: string | null
plan_step_id: string | null
target_agent_id: string
run_mode: direct_response | planned_step
instruction: string
context_bundle: object
workspace_ref: object | null
allowed_tools: list[string]
expected_artifacts: list[object]
```

Request rules:

- `run_id` must refer to a persisted `AgentRun`.
- `conversation_id` must match the source message or plan step.
- `source_message_id` is required for `direct_response`.
- `plan_step_id` is required for `planned_step`.
- `instruction` is normalized from the source message or plan step objective.
- `context_bundle` is scoped to the same conversation and must not reuse context
  across conversations.
- `workspace_ref` is an opaque workspace locator, not a raw provider payload.
- `allowed_tools` is the complete tool allowlist for the run.
- `expected_artifacts` is carried for future A8+ planning, but A7-0 does not
  create artifact records.
- Provider credentials, provider-specific request bodies, and response format
  translation fields are forbidden in `AgentRunRequest`.

## AgentRunEvent

Adapters emit only normalized `AgentRunEvent` records. The minimum event schema
and event sequence rules live in `docs/execution-event-protocol.md`.

Minimum event types are:

```text
run_created
run_started
adapter_error
provider_not_configured
assistant_message_delta
assistant_message_completed
run_failed
run_succeeded
```

`run_succeeded` may be emitted only after a real adapter/provider result. A
test-only fake success is allowed only in tests explicitly named
`adapter_success_contract`, and that success does not count as real Adapter
acceptance.

## Disabled And Not Configured

Agent profiles separate visibility from provider readiness:

```text
enabled=true, configured=false
```

This means the agent may appear in conversations and may be selected by routing
or planning, but it cannot execute a real provider call.

When `configured=false`:

- Creating an `AgentRun` is allowed.
- The run must become `failed`.
- `AgentRun.error_code` must be `provider_not_configured`.
- A `provider_not_configured` event must be written.
- A terminal `run_failed` event must be written.
- `run_succeeded` must not be written.
- No fake assistant answer may be written.

Suggested `provider_not_configured` payload:

```json
{
  "error_code": "provider_not_configured",
  "message": "Agent provider is not configured for execution.",
  "provider": null,
  "target_agent_id": "<agent_id>",
  "recovery_hint": "Configure provider credentials and model routing for this agent before starting a real run."
}
```

`execution_enabled=false` or `profile_only=true` remains a stronger planning
boundary from A6: those profiles may be assigned as planning owners, but an
execution controller must not claim they started a real run.

## Direct Response Mode

`TurnDecision(decision_type="direct_response")` creates:

```text
AgentRun(source_type=message, run_mode=direct_response)
```

Rules:

- The source is the persisted user message.
- The target agent comes from TurnRouter structured context.
- The path must call an Adapter with `AgentRunRequest`.
- On real Adapter success, write the assistant message from
  `assistant_message_completed`.
- On `configured=false`, write failed run state and `provider_not_configured`.
- It must not create `task`, `plan`, or `plan_step` records.
- It must not synthesize a fake assistant answer.

During A6.5, mentioned messages still bypass TurnRouter through A5 mention
dispatch for compatibility. That transitional behavior must not be used as the
final AgentRun protocol.

## Planned Step Mode

`run_mode="planned_step"` is used after `TurnDecision(decision_type="plan_task")`
has already created a durable plan step.

Rules:

- It is sourced from `source_type="plan_step"`.
- `plan_step_id` must point to an existing plan step in the same conversation.
- A planned-step run must not be created without a plan step.
- The run target must be the existing step assignment, not a default fallback.
- It must not reinterpret the original user message as a new route.
- On `configured=false`, it fails with `provider_not_configured` just like
  direct response.

## Product And Test Backends

Product default:

- A disabled or not-configured product adapter may fail explicitly.
- It must not return fake success or static assistant text.
- Adapter readiness may report `unsupported_provider`, `missing_credentials`,
  or `unavailable`, but a run created while readiness is `configured=false`
  fails through the A7 `provider_not_configured` run/event path.
- `profile_only` agents are not ready adapters, even if they are visible to
  planning and conversation membership.

Test backend:

- `TestAdapterBackend` may exist only under test configuration.
- It must never be the production default.
- It must not generate fake success except in tests explicitly named
  `adapter_success_contract`.
- A7 P0 primarily validates protocol shape and `provider_not_configured`
  behavior, not fake success.

## A7-0 Does Not Do

A7-0 does not implement:

- Artifact records or artifact cards.
- Diff records or patch application.
- Deployments.
- Long-running workers.
- SSE recovery.
- Multi-step execution engine.
- True Codex/OpenCode/Claude integration.
- Provider fallback.
- Fake assistant answers.

## A7-2 Adapter Readiness Boundary

A7-2 freezes and implements Adapter readiness before any real provider adapter.

Readiness status meanings:

| Status | `configured` | Meaning |
| --- | --- | --- |
| `ready` | true | Reserved for a future real adapter with credentials and implementation available. |
| `not_configured` | false | Agent/provider is visible but not configured for execution. |
| `missing_credentials` | false | Provider is known, but credentials are missing. |
| `unsupported_provider` | false | Provider or adapter kind is not registered. |
| `unavailable` | false | Provider is known, but no real adapter implementation is available in this phase. |

Current phase behavior:

- `DisabledAdapter.health()` returns `status=not_configured`,
  `configured=false`, `error_code=provider_not_configured`, and empty
  capabilities.
- `GET /api/adapters` returns registered readiness summaries.
- `GET /api/agents/{agent_id}/adapter-health` returns readiness for one agent
  profile.
- `POST /api/runs` still fails with `provider_not_configured` when
  `AdapterHealth.configured=false`.
- No real Codex/OpenCode/Claude adapter, artifact, diff, deploy, fake success,
  fake assistant answer, or provider fallback is introduced.

## A7-3 Real Direct Response Adapter Boundary

Acceptance ID:

```text
A7 real direct_response adapter only
```

A7-3 adds the first real direct-response adapter implementations while keeping
the same `AgentRunRequest` boundary. Provider-specific request bodies, API keys,
CLI command details, and response translations remain behind the Adapter
boundary and are resolved from `ProviderConfig`.

Supported adapter kinds in this stage:

| Adapter kind | Backend type | Scope |
| --- | --- | --- |
| `custom_openai` | `model_agent_backend` | OpenAI-compatible chat completions for ordinary answer agents. |
| `codex_cli` | `coding_agent_backend` | Local Codex CLI direct responses in read-only sandbox. |
| `claude_code_cli` | `coding_agent_backend` | Local Claude Code direct responses with tools and MCP disabled. |
| `disabled` | `model_agent_backend` | Explicit not-configured failure path. |

`tool_integration` backends such as lark-cli, git, and deployment CLIs are not
Agent Adapters in A7-3.

Readiness rules:

- `ready` is returned only after a real lightweight direct-response probe
  succeeds.
- Installed CLI binaries are not enough to report `ready`.
- Logged-in CLI status is not enough to report `ready`; the non-interactive
  direct-response probe must complete without long retry loops.
- Missing API credentials, missing executables, auth failures, timeouts, and
  network failures are explicit non-ready states and must not fall back to
  `DisabledAdapter` success.

Direct-response safety:

- Codex uses `codex -a never exec --json --cd <workspace_dir>
  --skip-git-repo-check --sandbox read-only --ephemeral --color never <prompt>`.
- Claude Code uses `<claude.exe> -p <prompt> --output-format stream-json
  --verbose --no-session-persistence --permission-mode dontAsk --tools=
  --strict-mcp-config`.
- Claude Code real CLI execution is manually gated by
  `AGENTHUB_ENABLE_CLAUDE_CODE_REAL_CLI=1`. Without that env, AgentHub treats
  Claude Code as currently unavailable and returns `run_timed_out` after
  preflight without starting `claude.exe`.
- Subprocesses are launched with argv lists and `shell=False`.
- A7-3 does not use `danger-full-access`, `workspace-write`,
  `--dangerously-skip-permissions`, Edit, Write, Bash, or MCP write tools for
  direct responses.

Success and failure rules:

- `assistant_message_completed` may be emitted only from real backend final
  assistant content.
- `run_succeeded` may be persisted only after a completed assistant message for
  `direct_response`.
- A persisted assistant chat message is written only after
  `assistant_message_completed`, `run_succeeded`, and `AgentRun.status=succeeded`.
- Failed, timed-out, auth-failed, invalid-response, and partial-delta-only runs
  do not create assistant messages.
- A7-3 does not create artifacts, diffs, deployments, planned-step workspace
  writes, fake adapters, mock success, or local canned answers.

## A7-3.1 Multi-Provider Custom OpenAI Boundary

Acceptance ID:

```text
A7 multi-provider custom_openai direct_response only
```

A7-3.1 keeps the same `AgentRunRequest` boundary and adds explicit
multi-provider configuration for OpenAI-compatible model agents. Provider URLs,
model names, credential source names, credentials, and wire request details stay
behind `ProviderConfig` and the `custom_openai` Adapter.

Supported custom OpenAI provider keys:

| Provider key | Agent profile ID | Required env names |
| --- | --- | --- |
| `qwen_turbo` | `qwen_turbo_agent` | `AGENTHUB_PROVIDER_QWEN_API_BASE`, `AGENTHUB_PROVIDER_QWEN_MODEL`, `AGENTHUB_PROVIDER_QWEN_API_KEY` |
| `volc_deepseek_flash` | `volc_deepseek_flash_agent` | `AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_BASE`, `AGENTHUB_PROVIDER_VOLC_DEEPSEEK_FLASH_MODEL`, `AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_KEY` |
| `volc_deepseek_pro` | `volc_deepseek_pro_agent` | `AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_BASE`, `AGENTHUB_PROVIDER_VOLC_DEEPSEEK_PRO_MODEL`, `AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_KEY` |
| `deepseek_official` | `deepseek_official_agent` | `AGENTHUB_PROVIDER_DEEPSEEK_API_BASE`, `AGENTHUB_PROVIDER_DEEPSEEK_MODEL`, `AGENTHUB_PROVIDER_DEEPSEEK_API_KEY` |

Rules:

- `credential_source` stores only an environment variable name or a future
  CredentialRef, never a raw secret value.
- Missing `api_base` or `model` resolves to `not_configured`.
- Missing API key resolves to `missing_credentials`.
- `ready` is returned only after the configured provider's real lightweight
  `/chat/completions` probe succeeds.
- Provider readiness is isolated by provider key; one ready provider never makes
  another provider ready.
- Direct-response success writes an assistant message only after
  `assistant_message_completed`, `run_succeeded`, and `AgentRun.status=succeeded`.
- The assistant message is associated to the run through `created_by_run_id` and
  mirrored in content JSON as `run_id`.
- This stage does not add provider fallback, fake success, static answers,
  artifacts, diffs, deployments, planned-step workspace writes, Codex
  workspace-write, or Claude Code write tools.
