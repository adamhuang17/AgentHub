# Acceptance Matrix

This file is the highest-priority implementation boundary. Implementation agents must not weaken, delete, rename, or bypass these acceptance targets. Every implementation task must reference one or more acceptance IDs.

Reference projects are limited to local open-source project profiles and source files listed in `AgentHub-多代理协作平台参赛工程方案.md`. Personal project directories are not part of this acceptance basis.

## Test Policy

- Acceptance tests live under `tests/acceptance/`.
- Acceptance tests are product-level tests and may fail until the corresponding module is implemented.
- Passing by hardcoded responses, fake success states, mocked adapters, in-memory-only state, or generated placeholder URLs is forbidden.
- External provider unavailable is a valid product state only when it is surfaced as an explicit error with provider, error code, and recovery hint.
- Tests may create data, artifacts, and releases; implementations must isolate them by test run ID.

## Test Layers

- Schema layer: `tests/schema/` fixes schema endpoints and Pydantic-facing shapes without invoking product workflows.
- Contract layer: `tests/contract/` fixes module protocols and boundaries without requiring full business chains to run.
- Service contract layer: `tests/service_contract/` verifies API-level service protocols that may create records, runs, or artifacts, but should avoid product-level end-to-end flows.
- Service smoke layer: `tests/smoke/` verifies API, web, and compose boot without claiming product behavior.
- Product acceptance layer: `tests/acceptance/` verifies real end-to-end behavior and is the implementation boundary.
- Reference integrity layer: `tests/integration/` verifies local reference source paths used by this matrix are present.

## Priority Scope

- P0: A1-A12 and A24.
- P0.5: A13-A17 and A23.
- P1: A18-A22.

## Current Core-Execution-Trace Boundary

Core-Execution-Trace adds durable conversation event replay and task trace
summaries before true SSE recovery. It supports
`GET /api/conversations/{id}/events`, `?after_sequence=`, and expanded
`GET /api/tasks/{id}` trace fields. This does not claim A12 SSE completion and
does not add deploy, workspace-write, Lark, MCP, or self-created agent behavior.

## Protected Files

Implementation agents must not modify these files except when the competition scope itself is intentionally renegotiated:

- `docs/acceptance-matrix.md`
- `docs/ai-coding-rules.md`
- `tests/acceptance/**`

Schema, contract, service contract, and smoke tests may be extended by implementation agents, but they must not contradict acceptance tests.

## Core Acceptance Matrix

| ID | Goal | Why It Is First | Test File |
| --- | --- | --- | --- |
| A1 | User can create a conversation and the conversation still exists after refresh/reload. | Locks IM entry and persistence. | `tests/acceptance/test_a1_conversation_persistence.py` |
| A2 | User can send a message and the message still exists after refresh/reload. | Locks the message spine. | `tests/acceptance/test_a2_message_persistence.py` |
| A3 | Conversation list is ordered by last activity and supports search/archive. | Locks IM product shape. | `tests/acceptance/test_a3_conversation_list_ui_contract.py` |
| A4 | Conversation members include user, Orchestrator, and multiple agents. | Locks single chat and group chat foundation. | `tests/acceptance/test_a4_conversation_members.py` |
| A5 | `@Agent` must dispatch to the mentioned agent. | Locks explicit agent dispatch. | `tests/acceptance/test_a5_mention_dispatch.py` |
| A6 | Without `@Agent`, Orchestrator generates Plan/Step and explains dispatch reasons. | Locks main-agent capability. | `tests/acceptance/test_a6_orchestrator_plan_dispatch.py` |
| A7 | At least two agent adapters accept the same `AgentRunRequest` protocol. | Locks unified adapter layer. | `tests/acceptance/test_a7_agent_adapter_contract.py` |
| A8 | Agent output enters Artifact Store and creates an artifact card in chat stream. | Locks non-text product output. | `tests/acceptance/test_a8_artifact_card_flow.py` |
| A9 | Code changes appear as Diff Artifact and do not directly overwrite main workspace. | Locks diff and workspace safety. | `tests/acceptance/test_a9_diff_artifact_flow.py` |
| A10 | Applying Diff/Patch requires review approval, audit logging, and creates at most one new `ArtifactVersion`. | Locks safety, auditability, and versioning. | `tests/acceptance/test_a10_apply_patch_permission.py`, `tests/acceptance/test_a10_review_gate_audit.py` |
| A11 | Artifact detail, version list, content download, and read-only preview are stable before any deployment flow. | Locks artifact consumption and preview safety before deployment. | `tests/acceptance/test_a11_artifact_preview_download.py` |
| A12-0 | Deployment release contract persists explicit failed releases without fake URLs or real cloud publish. | Locks the release protocol before provider integrations. | `tests/acceptance/test_a12_deployment_release_contract.py` |
| A12-1 | Static host provider publishes Artifact Store bytes to a real local URL. | Locks the first non-cloud deployment provider without builds, credentials, or workspace writes. | `tests/acceptance/test_a12_static_host_deployment.py` |
| A12 | Worker restart, browser refresh, and true SSE reconnect can recover task state. | Locks availability and engineering credibility. | `tests/acceptance/test_a12_event_recovery.py` |
| A13 | Different conversations never share context bundles, task context, or memory. | Locks privacy and multi-session correctness. | `tests/acceptance/test_a13_conversation_context_isolation.py` |
| A14 | Users can pin key messages and pinned messages enter context bundles and task context. | Locks requirement memory and contest prompt pinning. | `tests/acceptance/test_a14_pinned_key_messages.py` |
| A15 | Code block, file, image, webpage, Diff, and deployment cards are structured and backed by records. | Locks rich IM product surface. | `tests/acceptance/test_a15_rich_message_cards.py` |
| A16 | Users can create custom agents and mention-dispatch them. | Locks user-built Agent product loop. | `tests/acceptance/test_a16_user_created_agent.py` |
| A17 | Multiple agents editing the same file create a reviewable conflict without mutating the main version. | Locks real collaborative coding safety. | `tests/acceptance/test_a17_multi_agent_file_conflict.py` |
| A18 | Document range references produce localized document patch artifacts. | Locks partial document processing. | `tests/acceptance/test_a18_document_range_processing.py` |
| A19 | Feishu/Lark messages, bot cards, and cloud-doc range patches use real connector paths or explicit provider errors. | Locks external collaboration integration. | `tests/acceptance/test_a19_feishu_integration.py` |
| A20 | Agents communicate through persistent A2A envelopes and mailbox events. | Locks Agent-to-Agent protocol. | `tests/acceptance/test_a20_a2a_agent_protocol.py` |
| A21 | User interventions are queued and applied at task interruption points. | Locks proactive human steering. | `tests/acceptance/test_a21_user_intervention_interrupt_point.py` |
| A22 | A task node can be rewritten and redone while preserving lineage. | Locks task-node rollback and redo. | `tests/acceptance/test_a22_task_node_redo.py` |
| A23 | Mainstream model providers are registered and routed without silent fallback. | Locks broad model access. | `tests/acceptance/test_a23_model_provider_routing.py` |
| A24 | Task trace links message, plan, execution, agent/model, artifact, and error records. | Locks auditability and engineering proof. | `tests/acceptance/test_a24_task_traceability.py` |

## Detailed Acceptance Cases

### A1 Conversation Persistence

Input:

- `POST /api/conversations` with `title`, `mode`, and optional `agent_ids`.

Operation:

- Create a conversation.
- Fetch it by ID.
- Fetch conversation list with a new HTTP request.

Expected:

- Conversation ID is stable.
- Title, mode, status, and `last_active_at` are persisted.
- Conversation appears in list after reload.

Forbidden:

- Returning a transient object without database persistence.
- Reconstructing conversations from static seed data.
- Losing conversation after process restart.

Reference:

- OpenCode session persistence: `D:/Public Project/opencode-dev/packages/opencode/src/session/session.ts`
- OpenHands conversation service: `D:/Public Project/OpenHands-main/openhands/app_server/app_conversation/app_conversation_service.py`

### A2 Message Persistence

Input:

- Existing conversation ID.
- `POST /api/conversations/{id}/messages` with text content.

Operation:

- Send message.
- Fetch messages through a new HTTP request.

Expected:

- Message has stable ID, sender, content, type, and timestamp.
- Message remains visible after reload.

Forbidden:

- Keeping messages only in frontend state.
- Collapsing all messages into one summary without raw message persistence.

Reference:

- OpenCode message schema: `D:/Public Project/opencode-dev/packages/opencode/src/session/message-v2.ts`
- Cline message rendering contract: `D:/Public Project/cline-main/apps/vscode/webview-ui/src/components/chat/chat-view/components/messages/MessageRenderer.tsx`

### A3 Conversation List Contract

Input:

- Multiple conversations with different titles and activity times.

Operation:

- Create conversations.
- Send a message to one conversation.
- Query conversation list.
- Search by title.
- Archive one conversation.

Expected:

- Most recently active conversation appears first.
- Search returns matching titles.
- Archived conversation is excluded from normal list and retrievable when archive filter is enabled.

Forbidden:

- Sorting by create time only.
- Search only on frontend after loading all records.
- Archive implemented as deletion.

Reference:

- OpenCode session list UI: `D:/Public Project/opencode-dev/packages/app/src/pages/session/session-side-panel.tsx`

### A4 Conversation Members

Input:

- Group conversation with at least two enabled agents.

Operation:

- Create group conversation.
- Fetch members.

Expected:

- Members include the user, Orchestrator, and at least two agents.
- Each agent has ID, name, provider, avatar or initials, and capability tags.

Forbidden:

- Treating agents as plain text names in messages.
- Missing Orchestrator membership.

Reference:

- Ruflo coordinator topology: `D:/Public Project/ruflo-main/v3/@claude-flow/swarm/src/topology-manager.ts`
- OpenCode agent configuration: `D:/Public Project/opencode-dev/packages/opencode/src/agent`

### A5 Mention Dispatch

Input:

- Message containing `@Agent`.
- Mention metadata with the target agent ID.

Operation:

- Send mentioned message.
- Fetch created task and plan.

Expected:

- At least one step is assigned to the mentioned agent.
- Dispatch reason explicitly records mention-based dispatch.
- Orchestrator must not silently override the mentioned agent.

Forbidden:

- Ignoring mention metadata.
- Choosing a different agent because it is easier to call.
- Treating the current A6.5 TurnRouter bypass as final product logic.
- Faking `@Agent` direct responses before AgentRun/Adapter exists.
- Breaking current A5 mention dispatch acceptance during migration.

Compatibility note:

- In the current A6.5 stage, messages with non-empty `mentions` bypass TurnRouter
  and continue through A5 mention dispatch.
- This preserves A5 acceptance before AgentRun/Adapter is implemented.
- This is transitional compatibility, not the final product behavior.
- Future A5.5/A7 acceptance should cover `@Agent + simple question` creating a
  direct AgentRun, not task/plan/step.

Reference:

- Cline team agent spawning: `D:/Public Project/cline-main/sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts`

### A6 Orchestrator Plan Dispatch

Input:

- Message without mention.

Operation:

- Send task-like message.
- Fetch task, plan, and steps.

Expected:

- Orchestrator creates a plan.
- Plan contains ordered or DAG-linked steps.
- Each assigned step has dispatch reason based on capability, health, or permission.
- Capability dispatch may assign only agents with `enabled=true`,
  `configured=true`, `execution_enabled=true`, and `health_status` in
  `configured`, `healthy`, or `ready`.
- Capability-matched agents that are not executable create blocked steps with
  explicit `blocked_reason` such as `agent_not_configured`,
  `agent_execution_disabled`, or `agent_unavailable`.
- When no enabled executable agent matches the structured capability request,
  the step is blocked with `no_capability_match`.

Forbidden:

- Directly sending all work to a default agent without plan.
- Returning a plan only as chat text.
- Assigning profile-only, unconfigured, execution-disabled, or unhealthy agents
  to `plan_step.assigned_agent_id` through capability dispatch.

Reference:

- Dify workflow entry: `D:/Public Project/dify-main/api/core/workflow/workflow_entry.py`
- Ruflo unified coordinator: `D:/Public Project/ruflo-main/v3/@claude-flow/swarm/src/unified-coordinator.ts`

### A7 Agent Adapter Contract

Input:

- Same `AgentRunRequest` payload sent to two enabled adapters.

Operation:

- Start two runs through adapter endpoints.
- Read run events.

Expected:

- Both adapters accept the same request fields.
- Both emit `run_started`.
- Completion is `run_succeeded` or explicit provider error, never fake success.
- After direct_response is implemented, `@Agent + simple question` creates
  `AgentRun(source_type="message", run_mode="direct_response")` and does not
  create task/plan/step.
- `@Agent + complex task` remains `plan_task` and may create task/plan/step.

Forbidden:

- Adapter-specific request fields leaking into Orchestrator.
- Treating provider-not-configured as success.
- Creating a fake assistant answer without a real Adapter result.
- Using current A5 mention bypass as final direct_response behavior.

Reference:

- Cline agent runtime: `D:/Public Project/cline-main/sdk/packages/agents/src/agent-runtime.ts`
- 9Router provider facade: `D:/Public Project/9router-master/open-sse/handlers/chatCore.js`

A7-0 design boundary:

- A7-0 freezes `AgentRun`, `AgentRunRequest`, `AgentRunEvent`, and Adapter
  interface design only.
- A7-0 does not declare A7 implemented or passed.
- `configured=false` may still create a run, but it must fail with
  `provider_not_configured`, write a `provider_not_configured` event, and must
  not write `run_succeeded` or a fake assistant answer.
- A7-0 does not implement artifacts, diffs, deployments, long-running workers,
  SSE recovery, multi-step execution, or true Codex/OpenCode/Claude integration.

A7-1.1 contract hardening boundary:

- Current A7 run creation uses the unified `POST /api/runs` entry for both
  `source_type=message` direct responses and `source_type=plan_step` planned
  steps.
- `POST /api/agents/{agent_id}/runs` is not a current A7 creation entry and
  must not be reintroduced as a compatibility wrapper for this phase.
- `TestTurnRouterBackend` is request-injection-only: it may be used only when
  `AGENTHUB_ENV=test`, `AGENTHUB_ENABLE_TEST_TURN_ROUTER_BACKEND=1`, and the request
  body explicitly supplies `turn_decision`.
- `AGENTHUB_TURN_ROUTER_BACKEND=test` does not make the router globally configured;
  ordinary messages without `turn_decision`,
  `turn_route`, or `orchestrate` are persisted as messages only.

A7-2 adapter readiness boundary:

- Adapter readiness is exposed through `AdapterHealth` with
  `ready`, `not_configured`, `missing_credentials`, `unsupported_provider`, and
  `unavailable` statuses.
- `GET /api/adapters` returns registered readiness summaries.
- `GET /api/agents/{agent_id}/adapter-health` returns one agent profile's
  readiness.
- `profile_only` and `configured=false` profiles are not ready adapters.
- When readiness has `configured=false`, `POST /api/runs` still creates a failed
  run with `error_code=provider_not_configured`, writes
  `provider_not_configured` and `run_failed`, and writes no fake assistant
  answer.
- A7-2 does not add a real Codex/OpenCode/Claude adapter, artifact, diff,
  deploy, fake success, or provider fallback.

A7-3.1 multi-provider custom OpenAI boundary:

- `custom_openai` direct response supports the provider keys `qwen_turbo`,
  `volc_deepseek_flash`, `volc_deepseek_pro`, and `deepseek_official` through
  ProviderConfig-resolved environment variable names.
- Provider-specific URL/model/credential details remain outside
  `AgentRunRequest`.
- Missing provider env produces explicit `not_configured` or
  `missing_credentials` readiness, never fallback.
- A provider reports `ready` only after its own real direct-response probe
  succeeds.
- A successful direct response writes an assistant message associated with the
  AgentRun; failed runs write no assistant message.
- A7-3.1 does not create artifacts, diffs, deployments, planned-step
  workspace-write, fake success, static answers, or provider fallback.

A7-3.4 real adapter runtime final verification:

- `custom_openai` real direct-response success is verified for `qwen_turbo`,
  `volc_deepseek_flash`, `volc_deepseek_pro`, and `deepseek_official`.
- Each verified `custom_openai` success writes exactly one assistant message
  linked by `created_by_run_id`, emits `assistant_message_completed` before
  `run_succeeded`, and creates no task, plan, step, artifact, diff, or deploy
  records.
- `codex_cli` real runtime is verified with a configured executable and
  configured Codex login state. In the final local recheck, Codex reached the
  real CLI runtime, emitted `assistant_message_completed` before
  `run_succeeded`, and wrote exactly one assistant message. This is recorded as
  runtime success verified.
- `codex_cli` direct response remains read-only and must not include
  `workspace-write` or `danger-full-access`.
- `claude_code_cli` real runtime is manually gated by
  `AGENTHUB_ENABLE_CLAUDE_CODE_REAL_CLI=1`. By default, AgentHub treats Claude
  Code as currently unavailable and returns `run_timed_out` after preflight
  without starting `claude.exe`; when the env is set, a later verification may
  retry the real CLI path.
- `claude_code_cli` direct response keeps `--tools=` and
  `--strict-mcp-config`, and must not enable Edit, Write, Bash, MCP write
  tools, or `--dangerously-skip-permissions`.
- A7 remains limited to `direct_response`. Planned-step read-only execution is
  reserved for A7-4, while planned-step workspace-write, artifacts, diffs, and
  deployments remain A8+ scope.
- No real adapter runtime failure may fall back to another provider, emit a
  canned answer, or be marked as fake success.

### A8 Artifact Card Flow

Input:

- User asks an agent to create a document or web artifact.

Operation:

- Send message.
- Wait for task completion.
- Fetch artifacts and messages.

Expected:

- Artifact metadata is persisted.
- Message stream contains an `artifact_card` referencing the artifact ID.
- Artifact content is retrievable through Artifact API.

Forbidden:

- Returning artifact-like markdown only inside a text message.
- Creating cards with missing artifact records.

Reference:

- Artifact-centric state pattern: `04-AI_System_Knowledge/Patterns/Artifact_Centric_State_Pattern.md`
- OpenHands file store: `D:/Public Project/OpenHands-main/openhands/app_server/file_store/local.py`

A8-0 / A8-1 implementation boundary:

- Direct-response AgentRun success may create a read-only artifact only when
  final assistant output exists and the run explicitly declares
  `expected_artifacts`.
- Failed, timed-out, auth-failed, provider-not-configured, and invalid-success
  runs create no artifact.
- Assistant messages remain persisted as text messages and may reference
  artifacts through structured message references/cards.
- Artifact content is stored in the local Artifact Store with checksum-backed
  `ArtifactVersion` records; large content is not embedded in message content.
- This boundary does not implement Diff apply, Patch apply, Deploy,
  workspace-write, permission approval, generated publish URLs, or artifact
  mutation.

### A9 Diff Artifact Flow

Input:

- Existing source artifact.
- User asks for a code change.

Operation:

- Request modification.
- Fetch patch artifacts and source versions.

Expected:

- A patch/diff artifact is created.
- Main source artifact version is unchanged before apply.
- Patch records target artifact and base version.

Forbidden:

- Agent directly overwriting main workspace.
- Hiding file changes in natural language.

Reference:

- OpenCode patch tool: `D:/Public Project/opencode-dev/packages/opencode/src/tool/apply_patch.ts`
- Cline apply-patch executor: `D:/Public Project/cline-main/sdk/packages/core/src/extensions/tools/executors/apply-patch.ts`

A9-0 / A9-1 implementation boundary:

- Current scope is read-only Diff Artifact Preview only.
- `POST /api/artifacts/diff` creates a `diff_preview` or `source_diff`
  artifact from two existing `ArtifactVersion` records.
- `GET /api/artifacts/{id}/diff` returns structured diff metadata:
  `diff_artifact_id`, base/target artifact and version IDs, `files[]`,
  `hunks[]`, additions, deletions, and checksum.
- `GET /api/artifacts/{id}/content` remains readable for diff artifacts.
- Messages may reference diff artifacts and return `diff_card` /
  `diff_cards`; full diff text must not be embedded in message content.
- Base and target artifact contents are read from Artifact Store and verified
  against persisted checksums before diff creation. Optional request checksum
  preconditions must also match.
- Missing base/target versions, checksum mismatch, and binary/unsupported
  content return explicit error codes and create no diff artifact.
- This boundary does not implement Patch apply, Diff apply, workspace-write,
  permission approval, deployments, generated publish URLs, or mutation of
  existing source artifact versions.

### A10 Apply Patch Permission

Input:

- Existing source artifact and patch artifact.

Operation:

- Attempt to apply patch.
- Approve review request.
- Apply again.
- Retry the same approved apply.
- Exercise stale base, checksum mismatch, and conflict boundaries in contract tests.

Expected:

- First attempt returns `review_required`, creates `ReviewRequest`, writes audit, and creates no new `ArtifactVersion`.
- Rejected review writes audit and creates no new `ArtifactVersion`.
- Approved apply writes audit and creates exactly one new `ArtifactVersion` with `parent_version_id`.
- Duplicate approved apply returns the existing `PatchApplication(applied)` and does not create a second version.
- Stale base returns `artifact_apply_stale_base` and creates no version.
- Checksum mismatch returns `artifact_apply_checksum_mismatch` and creates no version.
- Conflict returns `artifact_apply_conflict` and creates no version.
- Applied version, `PatchApplication(applied)`, and audit log are committed consistently.

Forbidden:

- Applying write operations without review.
- Mutating version content without new version record.
- Writing to workspace or deployment paths.
- Codex `workspace-write` / `danger-full-access`.
- Claude Edit, Write, Bash, or MCP write tools.

Reference:

- OpenCode permission evaluation: `D:/Public Project/opencode-dev/packages/opencode/src/permission/evaluate.ts`
- Cline interactive approvals: `D:/Public Project/cline-main/apps/cli/src/runtime/interactive/approvals.ts`

### A11 Artifact View, Download, and Read-only Preview

A11-0 / A11-1 / A11.5 implementation boundary:

- Artifact detail, version listing, content download, and read-only preview are
  the current A11 scope.
- Deployment release creation, publish URLs, and preview publishing remain out
  of scope for this boundary.

Input:

- Existing `document`, `source_file`, `diff_preview`, or `source_diff`
  artifacts persisted in Artifact Store.
- An approved A10 patch application that creates a new `ArtifactVersion`.

Operation:

- Fetch `GET /api/artifacts/{id}`.
- Fetch `GET /api/artifacts/{id}/versions`.
- Fetch `GET /api/artifacts/{id}/content`.
- Fetch `GET /api/artifacts/{id}/download`, with optional positive `?version=`.
- Fetch `GET` or `POST /api/artifacts/{id}/preview`.
- Click the Web Artifact Card `Download` action.

Expected:

- Artifact detail includes `current_version_id`, `version`, `checksum`,
  `created_by_run_id`, `type`, `mime_type`, and `status`.
- Version list returns all immutable versions with `parent_version_id` and
  `checksum`.
- Content reads the current version by default and verifies checksum before
  returning content.
- Download reads Artifact Store bytes for the selected version, returns raw
  bytes, and sets `Content-Type` plus `Content-Disposition` from persisted
  artifact metadata.
- Source file, document, and binary file downloads are supported without
  building, publishing, or writing into the workspace.
- `document` and `source_file` previews return read-only UTF-8 text from
  Artifact Store.
- `diff_preview` and `source_diff` previews return structured diff data from
  Artifact Store.
- Checksum mismatch fails with an explicit preview/content/download error code.
- Unsupported or binary previews fail with `artifact_preview_unsupported`.
- Applied A10 patch versions appear in the version list with
  `parent_version_id`.
- Web Artifact Cards render a real `Download` action that calls the download
  endpoint and surfaces errors explicitly instead of faking success.

Forbidden:

- Building, deploying, publishing, or returning external preview URLs.
- Writing artifact preview/download content to the workspace.
- Reading credentials to generate previews.
- Marking previewed artifacts as `published`.
- Bypassing the A10 review gate to create a new version.

Reference:

- OpenHands file store: `D:/Public Project/OpenHands-main/openhands/app_server/file_store/local.py`
- Cline message renderer: `D:/Public Project/cline-main/apps/vscode/webview-ui/src/components/chat/chat-view/components/messages/MessageRenderer.tsx`

### A12-0 Deployment Release Contract

A12-0 implementation boundary:

- Deployment release schema, repository, disabled provider contract, and direct
  deploy/read API are in scope.
- Real Vercel, Cloudflare, shell build, workspace-write, credential reads,
  preview publishing, and fake published URLs are out of scope.

Input:

- Existing Artifact Store record and current `ArtifactVersion`.
- Deploy request with optional provider name.

Operation:

- `POST /api/artifacts/{id}/deploy`.
- `GET /api/deployments/{id}`.

Expected:

- `DeploymentRelease` returns exactly `id`, `artifact_id`,
  `artifact_version_id`, `provider`, `status`, `url`, `error_code`,
  `created_at`, and nullable `published_at`.
- Status is one of `created`, `publishing`, `published`, or `failed`.
- Unsupported artifact types fail with `deployment_artifact_unsupported`.
- Unconfigured providers fail with `deployment_provider_not_configured`.
- Missing provider credentials are represented by
  `deployment_credentials_missing` in the provider contract.
- Failed releases have `url = null` and `published_at = null`.
- A `deployment_release` artifact may be created only by the deployment
  service after the release status is explicit; failed attempts create only
  `failed` release artifacts.

Forbidden:

- Returning placeholder or fake deployment URLs.
- Treating preview URLs as published URLs.
- Falling back to a fake provider.
- Running shell builds or cloud provider CLIs.
- Writing deployment content into the workspace.
- Reading credentials in this phase.
- Marking a failed attempt as `published`.

### A12-1 Static Host Deployment Provider

A12-1 implementation boundary:

- `static_host` is the only real provider in this phase.
- It reads the current `ArtifactVersion` from Artifact Store, verifies checksum,
  and copies those bytes to `AGENTHUB_STATIC_DEPLOY_DIR`.
- It serves published files through `GET /static-deployments/{release_id}/...`.
- It uses `AGENTHUB_PUBLIC_BASE_URL` for returned URLs when set, otherwise
  `http://{HOST}:{PORT}`.
- It does not call Vercel, Cloudflare, provider CLIs, shell builds, cloud
  credentials, preview URLs, Codex `danger-full-access`, Claude write tools, or
  workspace write paths.

Input:

- Existing deployable artifact: `web_preview`, `web_app`, or `static_site`.
- Deploy request with `provider = static_host`.
- `AGENTHUB_STATIC_DEPLOY_DIR` set to a writable non-workspace directory.

Operation:

- `POST /api/artifacts/{id}/deploy`.
- `GET /api/deployments/{id}`.
- `GET` the returned deployment URL.

Expected:

- Release reaches `published`.
- `url` is non-empty and HTTP GET returns the source content.
- `published_at` is non-null.
- A status `available` `deployment_release` artifact is created.
- Release artifact JSON records provider, URL, source artifact, and source version.
- Missing static dir fails with `deployment_provider_not_configured`.
- Unsupported artifact fails with `deployment_artifact_unsupported`.
- Checksum mismatch fails with `deployment_artifact_checksum_mismatch`.
- Write failure fails with `deployment_publish_failed`.
- Failed releases have `url = null` and `published_at = null`.

Forbidden:

- Returning placeholder or fake deployment URLs.
- Treating preview URLs as published URLs.
- Running shell builds or cloud provider CLIs.
- Reading cloud credentials.
- Writing deployment content into the workspace.
- Marking `published` without creating a `deployment_release` artifact.

### A12 Event Recovery

Input:

- Long-running task.

Operation:

- Open `GET /api/conversations/{id}/events/stream` with `Accept: text/event-stream`.
- Disconnect.
- Reconnect to the same SSE endpoint with `after={sequence}` cursor.
- Fetch durable event replay through REST.
- Fetch task status.

Expected:

- Event sequence is monotonic.
- Reconnect returns missed events without duplicates.
- SSE response has `Content-Type: text/event-stream`.
- Task state from event stream matches task API.

Forbidden:

- Process-local-only event streams.
- Lost events after browser refresh.
- Simulating reconnect only with REST `after=sequence` without validating a real SSE stream.

Reference:

- OpenHands event store: `D:/Public Project/OpenHands-main/openhands/app_server/event/event_store.py`
- Cline session events: `D:/Public Project/cline-main/apps/cli/src/runtime/session-events.ts`

### A13 Conversation Context Isolation

Input:

- Two conversations with unique context tokens.
- A task created in one conversation.

Operation:

- Write different messages to each conversation.
- Fetch each conversation context.
- Fetch task context for one conversation.

Expected:

- Each conversation context contains only its own token.
- Task context contains only the source conversation's token.
- Memory retrieval and summaries are scoped by conversation and workspace.

Forbidden:

- Global memory injection without conversation/workspace filtering.
- Querying all recent messages and filtering only in the frontend.
- Reusing an agent run context bundle across conversations.

Reference:

- OpenCode session schema: `D:/Public Project/opencode-dev/packages/opencode/src/session/schema.ts`
- OpenCode message store: `D:/Public Project/opencode-dev/packages/opencode/src/session/message-v2.ts`

### A14 Pinned Key Messages

Input:

- A key message in a conversation.
- Pin request with reason.

Operation:

- Pin the message.
- Fetch pins.
- Fetch conversation context and task context.

Expected:

- Pin record is durable and includes actor, message, conversation, reason, and timestamp.
- Pinned content enters context bundles ahead of ordinary recent messages.
- Agent task context references pinned message IDs.

Forbidden:

- UI-only pin state.
- Treating pins as bookmarks that agents cannot see.
- Losing pins after refresh or worker restart.

Reference:

- Lark pin API reference: `D:/Public Project/cli-main/skills/lark-im/SKILL.md`
- OpenClaw Feishu pins: `D:/Public Project/openclaw-main/extensions/feishu/src/pins.ts`

### A15 Rich Message Cards

Input:

- Structured messages for code block, file, image, webpage, Diff, and deployment card.
- Backing artifacts or deployment releases where required.

Operation:

- Persist backing artifacts/releases.
- Create card messages.
- Fetch messages and backing records.

Expected:

- Card payloads have stable schema and type-specific fields.
- File/image/Diff cards reference persisted artifacts.
- Deployment cards reference persisted `DeploymentRelease`.
- Webpage cards store URL metadata and renderable title.

Forbidden:

- Rendering rich cards from unstructured markdown only.
- Cards referencing missing artifacts or releases.
- Base64 blobs stored only in chat message rows when Artifact Store is required.

Reference:

- Cline message renderer: `D:/Public Project/cline-main/apps/vscode/webview-ui/src/components/chat/chat-view/components/messages/MessageRenderer.tsx`
- OpenHands file store: `D:/Public Project/OpenHands-main/openhands/app_server/file_store/local.py`

### A16 User-Created Agent

Input:

- Custom agent definition with name, system prompt, model, tools, and capability tags.

Operation:

- Create custom agent.
- List enabled custom agents.
- Add it to a conversation.
- Mention it in a message.
- Fetch task plan.

Expected:

- Agent profile is durable.
- Agent appears in registry and conversation members.
- Mention dispatch assigns at least one step to the custom agent.
- Provider-not-configured becomes explicit task failure, not fake success.

Forbidden:

- Custom agents that only exist in frontend state.
- Ignoring user-defined prompt/tools.
- Falling back to a default agent while claiming the custom agent ran.

Reference:

- Cline spawn-agent tool: `D:/Public Project/cline-main/sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts`
- Ruflo MCP agent tools: `D:/Public Project/ruflo-main/v3/@claude-flow/cli/src/mcp-tools/agent-tools.ts`

### A17 Multi-Agent File Conflict

Input:

- A source artifact.
- Two enabled agents assigned parallel edits to the same file path.

Operation:

- Start parallel task.
- Let both agents propose incompatible patches.
- Fetch source artifact and conflict records.

Expected:

- Main artifact version remains unchanged.
- Conflict record or conflict artifact is created.
- Conflict lists target artifact, base version, conflicting paths, and agent IDs.
- Status requires user or reviewer resolution.

Forbidden:

- Last-writer-wins overwrite.
- Auto-merging incompatible patches without review.
- Hiding conflict in plain chat text.

Reference:

- Cline team runtime parallel runs: `D:/Public Project/cline-main/sdk/packages/core/src/extensions/tools/team/multi-agent.ts`
- OpenCode patch tool: `D:/Public Project/opencode-dev/packages/opencode/src/tool/apply_patch.ts`

### A18 Document Range Processing

Input:

- Document artifact.
- Artifact range reference such as a markdown heading, paragraph range, or document block ID.

Operation:

- Send a request that targets only the selected range.
- Wait for agent output.
- Fetch document patch artifact.

Expected:

- Patch artifact records target artifact, base version, and affected ranges.
- Unselected sections are not modified before apply.
- Chat stream includes a document patch card.

Forbidden:

- Rewriting the whole document when a range is selected.
- Applying the patch without permission/versioning.
- Dropping range metadata before adapter execution.

Reference:

- OpenClaw Feishu docx operations: `D:/Public Project/openclaw-main/extensions/feishu/src/docx.ts`
- Lark markdown patch reference: `D:/Public Project/cli-main/skills/lark-markdown/references/lark-markdown-patch.md`

### A19 Feishu Integration

Input:

- Feishu/Lark message, bot card, and cloud-doc range patch requests.

Operation:

- Fetch connector status.
- Send message request.
- Send bot card request.
- Send cloud-doc range patch request.

Expected:

- Connector exposes capabilities: `message.send`, `bot.card`, `cloud_doc.range_patch`.
- Configured connector uses real Feishu/Lark API paths.
- Unconfigured connector returns explicit provider error with recovery hint.
- Idempotency keys prevent duplicate external sends.

Forbidden:

- Dry-run presented as sent message.
- Local-only cards pretending to be Feishu bot cards.
- Swallowing Feishu API errors.

Reference:

- Lark IM skill: `D:/Public Project/cli-main/skills/lark-im/SKILL.md`
- Lark message send reference: `D:/Public Project/cli-main/skills/lark-im/references/lark-im-messages-send.md`
- OpenClaw Feishu streaming card: `D:/Public Project/openclaw-main/extensions/feishu/src/streaming-card.ts`
- OpenClaw Feishu docx: `D:/Public Project/openclaw-main/extensions/feishu/src/docx.ts`

### A20 A2A Agent Protocol

Input:

- Two agents in the same conversation.
- A2A envelope with sender, recipient, message type, correlation ID, and payload.

Operation:

- Send A2A message.
- Fetch recipient mailbox.
- Fetch conversation event log.

Expected:

- Envelope is durable and routable.
- Recipient mailbox contains the message.
- Conversation events include A2A creation event.
- Correlation ID is preserved for replies and traces.

Forbidden:

- Passing agent-to-agent messages only through prompt text.
- Missing persistence or delivery state.
- Cross-conversation A2A delivery without membership checks.

Reference:

- Cline team mailbox: `D:/Public Project/cline-main/sdk/packages/core/src/extensions/tools/team/multi-agent.ts`
- Ruflo message bus: `D:/Public Project/ruflo-main/v3/@claude-flow/swarm/src/unified-coordinator.ts`

### A21 User Intervention at Interrupt Point

Input:

- Running multi-step task.
- User supplemental context or correction.

Operation:

- Submit intervention with `apply_at=next_interrupt_point`.
- Poll intervention state.
- Fetch task events.

Expected:

- Intervention is durable and linked to task.
- Agent finishes the current atomic step before consuming it.
- Intervention state reaches `waiting_user_context` or `applied`.
- Event log records queued/applied state.

Forbidden:

- Abruptly killing the current run as the only intervention mechanism.
- Injecting user text into a running tool call mid-flight.
- Losing interventions during worker restart.

Reference:

- Cline interactive approvals: `D:/Public Project/cline-main/apps/cli/src/runtime/interactive/approvals.ts`
- Cline team pending steer message: `D:/Public Project/cline-main/sdk/packages/core/src/extensions/tools/team/multi-agent.ts`

### A22 Task Node Redo and Lineage

Input:

- Task with plan steps.
- User-edited prompt for one step.

Operation:

- Fetch plan.
- Redo one step with edited prompt.
- Fetch old step runs and task lineage.

Expected:

- Previous step/run remains readable.
- Redo creates new step/run with lineage to the previous step.
- Edited prompt and reason are durable.
- New artifact versions link to redo lineage when artifacts are produced.

Forbidden:

- Deleting old runs to make redo look clean.
- Mutating historical prompt text in place.
- Reusing old artifact version IDs for new output.

Reference:

- OpenCode revert: `D:/Public Project/opencode-dev/packages/opencode/src/session/revert.ts`
- OpenCode retry: `D:/Public Project/opencode-dev/packages/opencode/src/session/retry.ts`

### A23 Model Provider Routing

Input:

- Provider registry request.
- Model resolve request.
- Unsupported model request.

Operation:

- Fetch `GET /api/model-providers`.
- Resolve default agent model.
- Resolve unsupported model.

Expected:

- Registry includes mainstream providers: OpenAI, Anthropic, Gemini, OpenRouter, and Ollama at minimum.
- Provider entries expose API format, credential status, and model list.
- Default resolution returns provider/model/format and credential status.
- Unsupported model returns explicit error and never silently falls back.

Forbidden:

- Adapter-specific provider fields leaking into Orchestrator.
- Unknown model silently mapped to default provider.
- Treating missing credentials as successful model resolution.

Reference:

- 9Router providers: `D:/Public Project/9router-master/open-sse/config/providers.js`
- 9Router chat core: `D:/Public Project/9router-master/open-sse/handlers/chatCore.js`
- 9Router response translators: `D:/Public Project/9router-master/open-sse/translator/response/claude-to-openai.js`, `D:/Public Project/9router-master/open-sse/translator/response/openai-to-claude.js`

### A24 Task Traceability

Input:

- Chat-triggered task.

Operation:

- Send task message.
- Wait for terminal success or explicit failure.
- Fetch task trace.

Expected:

- Trace links message, task, plan, execution, agent/model routing, artifacts, permissions, deployment, and errors where present.
- Each trace item has trace ID, module, timestamp, and relevant entity IDs.
- Failure traces include error code and responsible module.

Forbidden:

- Debug logs as the only trace source.
- Unstructured trace text that cannot be queried by entity ID.
- Hiding adapter/provider failures outside the task trace.

Reference:

- Cline session events: `D:/Public Project/cline-main/apps/cli/src/runtime/session-events.ts`
- 9Router usage repo: `D:/Public Project/9router-master/src/lib/db/repos/usageRepo.js`
