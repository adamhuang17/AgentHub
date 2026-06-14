# Legacy MACIOS Migration Review

## Current Decision

No legacy module is approved for direct code migration into AgentHub at this stage.

This file now keeps a candidate migration review queue so implementation agents can reuse proven local assets without weakening the AgentHub product boundary. The default permission is pattern reuse only, not source copying.

## Review Basis

Reviewed legacy project:

- `D:/Agent-Hub`

Reviewed AgentHub target boundary:

- `D:/AgentHub/docs/acceptance-matrix.md`
- `D:/AgentHub/docs/implementation-scope.md`
- `D:/AgentHub/docs/module-boundary.md`
- `D:/AgentHub/tests/acceptance/**`
- `D:/AgentHub/tests/contract/**`

Reviewed local reference code for alignment:

- `D:/Public Project/opencode-dev/packages/opencode/src/tool/apply_patch.ts`
- `D:/Public Project/opencode-dev/packages/opencode/src/session/revert.ts`
- `D:/Public Project/9router-master/open-sse/config/providers.js`
- `D:/Public Project/9router-master/open-sse/handlers/chatCore.js`
- `D:/Public Project/cline-main/sdk/packages/core/src/extensions/tools/team/multi-agent.ts`
- `D:/Public Project/ruflo-main/v3/@claude-flow/swarm/src/unified-coordinator.ts`
- `D:/Public Project/openclaw-main/extensions/feishu/src/docx.ts`
- `D:/Public Project/openclaw-main/extensions/feishu/src/streaming-card.ts`
- `D:/Public Project/cli-main/skills/lark-im/SKILL.md`

## Status Values

- `approved_pattern_only`: The module shape is close enough to reimplement the design pattern, but source code must not be copied.
- `review_pending`: The module is promising but needs license, security, data-model, and acceptance coverage review before any use.
- `rejected`: Do not migrate code or pattern into the AgentHub mainline.
- `approved_code_migration`: Direct code migration is allowed after review. No candidate currently has this status.

## Candidate Migration Review Queue

| Candidate | MACIOS Source | Local Reference Alignment Checked | Target Module | Match | Status | Reason |
| --- | --- | --- | --- | --- | --- | --- |
| Durable event replay and sequence cursor | `D:/Agent-Hub/src/agent_hub/pilot/events/store.py` | `D:/Public Project/OpenHands-main/openhands/app_server/event/event_store.py`; `D:/Public Project/cline-main/apps/cli/src/runtime/session-events.ts` | `execution/event_store.py`, `execution/event_stream.py` | High pattern match | `approved_pattern_only` | Legacy `SQLiteEventStore` already has monotonic `sequence`, idempotency key, and list-after-cursor behavior that fits A12. Code is tied to Pilot entity registry and includes in-memory test implementation, so only the replay/cursor pattern is approved. |
| In-process event fan-out for SSE bridge | `D:/Agent-Hub/src/agent_hub/pilot/events/bus.py` | `D:/Public Project/cline-main/apps/cli/src/runtime/session-events.ts` | `execution/event_bus.py` | Medium pattern match | `approved_pattern_only` | Bounded subscriber queues and overflow handling fit SSE live fan-out. It is process-local and must sit behind durable replay, so it cannot be the source of truth. |
| Snapshot repository with optimistic concurrency | `D:/Agent-Hub/src/agent_hub/pilot/services/repository.py`; `D:/Agent-Hub/src/agent_hub/pilot/events/store.py` | `D:/Public Project/opencode-dev/packages/opencode/src/session/revert.ts` | `orchestration/repository.py`, `artifacts/version_repo.py` | Medium pattern match | `approved_pattern_only` | Expected-version writes and typed repository wrappers are useful for A10, A17, A22. Entity names are Pilot-specific and not compatible with AgentHub's conversation/task/artifact schema. |
| Artifact metadata, content materialization, checksum | `D:/Agent-Hub/src/agent_hub/pilot/services/artifacts.py` | `D:/Public Project/OpenHands-main/openhands/app_server/file_store/local.py`; `D:/Public Project/opencode-dev/packages/opencode/src/tool/apply_patch.ts` | `artifacts/store.py`, `artifacts/version_service.py` | High pattern match | `approved_pattern_only` | Legacy artifact store has metadata, checksum, storage key, read-back, and parent/supersede ideas that match A8-A10. Direct migration is blocked because it stores a single Artifact snapshot per version and includes memory fallback. |
| Diff permission and apply flow | `D:/Agent-Hub/src/agent_hub/pilot/services/approval.py`; `D:/Agent-Hub/src/agent_hub/pilot/services/execution.py` | `D:/Public Project/opencode-dev/packages/opencode/src/tool/apply_patch.ts` | `artifacts/diff_service.py`, `permissions/review_service.py` | Medium pattern match | `approved_pattern_only` | Legacy approval gate and OpenCode patch permission both support A9-A10. AgentHub must create Diff Artifact first and only then apply through permissioned versioning; legacy execution can only inform state transitions. |
| Skill registry timeout and error normalization | `D:/Agent-Hub/src/agent_hub/pilot/skills/registry.py` | `D:/Public Project/ruflo-main/v3/@claude-flow/mcp/src/tool-registry.ts`; `D:/Public Project/cline-main/sdk/packages/core/src/extensions/tools/team/multi-agent.ts` | `agents/tool_registry.py`, `mcp/tool_registry.py` | High pattern match | `approved_pattern_only` | `SkillSpec`, timeout handling, scoped listing, and normalized `SkillResult` are close to AgentHub tool adapter needs. It must be rewritten around AgentHub `AgentRunRequest`, permissions, and no dry-run-as-success rule. |
| Plan DAG validation and immutable state transitions | `D:/Agent-Hub/src/agent_hub/pilot/domain/state.py`; `D:/Agent-Hub/src/agent_hub/pilot/domain/models.py` | `D:/Public Project/dify-main/api/core/workflow/workflow_entry.py`; `D:/Public Project/ruflo-main/v3/@claude-flow/swarm/src/unified-coordinator.ts` | `orchestration/plan_model.py`, `orchestration/state_machine.py` | High pattern match | `approved_pattern_only` | `validate_plan_graph` and pure `transition` are a strong match for A6, A21, A22. Direct migration is blocked by Pilot-specific statuses, `AUTO_APPROVED`, and missing AgentHub conversation/member/A2A fields. |
| Task orchestrator idempotency and approval handoff | `D:/Agent-Hub/src/agent_hub/pilot/services/orchestrator.py` | `D:/Public Project/ruflo-main/v3/@claude-flow/swarm/src/unified-coordinator.ts` | `orchestration/task_service.py` | Medium pattern match | `approved_pattern_only` | Submit/deduplicate/plan/approval/run handoff maps to A5-A6 and A21. Direct migration is blocked because it assumes Workspace, Pilot plans, and auto-approve branches rather than IM-first conversations. |
| Execution DAG runner and upstream artifact resolver | `D:/Agent-Hub/src/agent_hub/pilot/services/execution.py` | `D:/Public Project/cline-main/sdk/packages/core/src/extensions/tools/team/multi-agent.ts`; `D:/Public Project/ruflo-main/v3/@claude-flow/swarm/src/unified-coordinator.ts` | `execution/worker.py`, `execution/step_runner.py` | Medium pattern match | `approved_pattern_only` | Topological execution, upstream artifact resolution, progress events, and retry reset are useful. Direct code is rejected for mainline because it contains dry-run handling and `auto-approved (demo)` flow. |
| Approval state machine and decision record | `D:/Agent-Hub/src/agent_hub/pilot/services/approval.py` | `D:/Public Project/cline-main/apps/cli/src/runtime/interactive/approvals.ts`; `D:/Public Project/opencode-dev/packages/opencode/src/tool/apply_patch.ts` | `permissions/review_service.py`, `permissions/audit_log.py` | Medium pattern match | `approved_pattern_only` | Request/decision/supersede concepts fit A10, A21, A22. Direct migration is blocked by `auto_approve_plan` and Pilot-specific plan/step coupling. |
| Feishu HTTP client endpoint mapping and structured error | `D:/Agent-Hub/src/agent_hub/connectors/feishu/client.py` | `D:/Public Project/cli-main/skills/lark-im/SKILL.md`; `D:/Public Project/openclaw-main/extensions/feishu/src/streaming-card.ts`; `D:/Public Project/openclaw-main/extensions/feishu/src/docx.ts` | `integrations/feishu/client.py` | Medium pattern match | `review_pending` | Real methods map to Feishu IM, Drive, and Docx endpoints and `FeishuApiError.to_error_details` fits A19. Direct code migration is not approved because the same file exports `FakeFeishuClient`; the production client must be split and security-reviewed first. |
| Feishu webhook normalization and card callback routing | `D:/Agent-Hub/src/agent_hub/connectors/feishu/service.py`; `D:/Agent-Hub/src/agent_hub/connectors/feishu/webhook.py`; `D:/Agent-Hub/src/agent_hub/connectors/feishu/longconn.py` | `D:/Public Project/openclaw-main/extensions/feishu/src/monitor.message-handler.ts`; `D:/Public Project/openclaw-main/extensions/feishu/src/card-ux-approval.ts` | `integrations/feishu/webhook_service.py` | Medium pattern match | `review_pending` | Inbound normalization and approval-card callbacks are valuable for P1 Feishu inbound binding. It currently imports Pilot domain/services and must be separated behind AgentHub connector DTOs. |
| Feishu approval/progress card pattern | `D:/Agent-Hub/src/agent_hub/connectors/feishu/approval_notifier.py`; `D:/Agent-Hub/src/agent_hub/connectors/feishu/progress_notifier.py`; `D:/Agent-Hub/src/agent_hub/pilot/skills/feishu_card.py` | `D:/Public Project/openclaw-main/extensions/feishu/src/streaming-card.ts`; `D:/Public Project/openclaw-main/extensions/feishu/src/sequential-queue.ts` | `integrations/feishu/cards.py`, `execution/progress_notifier.py` | Medium pattern match | `approved_pattern_only` | Card lifecycle and progress notification ideas fit A19 and A24. Direct migration is blocked by Pilot entity imports and must be rebuilt around AgentHub tasks, deployment releases, and trace events. |
| Model/provider routing registry | `D:/Agent-Hub/src/agent_hub/core/router.py`; `D:/Agent-Hub/src/agent_hub/pilot/services/model_gateway.py` | `D:/Public Project/9router-master/open-sse/config/providers.js`; `D:/Public Project/9router-master/open-sse/handlers/chatCore.js` | `model_router/provider_registry.py`, `model_router/resolve_service.py` | Low code match, high concept match | `approved_pattern_only` | Structured routing and provider-extra-body ideas are useful, but legacy code uses fallback/default behavior and fake/template gateways. Implement A23 from the 9Router-style provider registry, not by copying MACIOS router code. |
| Task trace projection | `D:/Agent-Hub/src/agent_hub/core/trace_store.py`; `D:/Agent-Hub/src/agent_hub/runtime/observability/tracing.py` | `D:/Public Project/9router-master/src/lib/db/repos/usageRepo.js`; `D:/Public Project/cline-main/apps/cli/src/runtime/session-events.ts` | `trace/trace_service.py`, `trace/projection_store.py` | Low direct match | `review_pending` | Legacy trace store is in-memory LRU and cannot satisfy A24 durability. The span shape can inform trace DTOs, but AgentHub needs a durable projection linked to messages/tasks/artifacts/errors. |
| Architecture boundary guard tests | `D:/Agent-Hub/tests/test_architecture.py` | `D:/AgentHub/docs/module-boundary.md`; `D:/AgentHub/tests/contract/test_module_boundaries.py` | `tests/contract/test_module_boundaries.py` | High pattern match | `approved_pattern_only` | AST import-boundary tests are directly relevant. Only the testing idea and rule style may be reused; paths and forbidden imports must follow AgentHub modules. |
| Memory conflict detection | `D:/Agent-Hub/src/agent_hub/memory/conflict_detector.py`; `D:/Agent-Hub/src/agent_hub/memory/vector_memory.py` | `D:/Public Project/opencode-dev/packages/opencode/src/session/revert.ts` | `memory/context_store.py`, `memory/conflict_service.py` | Medium concept match | `review_pending` | The add/update/noop idea may help long-term memory. A13 requires strict conversation isolation first, and the legacy detector falls back to ADD on errors, so it cannot be mainline until failure policy is redesigned. |
| Persistent markdown memory | `D:/Agent-Hub/src/agent_hub/memory/persistent.py` | `D:/Public Project/opencode-dev/packages/opencode/src/session/session.ts` | `memory/archive_export.py` | Low match | `rejected` | Obsidian markdown storage is useful as export/import tooling, but it is not a durable product store for A13/A14 context isolation. Do not use it for AgentHub runtime memory. |
| Fake skill set and fake provider outputs | `D:/Agent-Hub/src/agent_hub/pilot/skills/fake.py`; `D:/Agent-Hub/src/agent_hub/pilot/services/model_gateway.py` | Rejected by `D:/AgentHub/docs/ai-coding-rules.md` | None | No match | `rejected` | Contains fake artifacts, fake Drive URLs, fake Feishu tokens, and template fallback paths. This is explicitly forbidden in AgentHub mainline. |
| Auto-approve demo path | `D:/Agent-Hub/src/agent_hub/pilot/services/approval.py`; `D:/Agent-Hub/src/agent_hub/pilot/services/execution.py`; `D:/Agent-Hub/src/agent_hub/pilot/services/orchestrator.py` | Rejected by A10 permission tests | None | No match | `rejected` | `auto_approve_plan` and `auto-approved (demo)` bypass the product permission requirement. Keep only as a cautionary example. |

## Direct Code Migration Allowlist

No candidate is currently `approved_code_migration`.

Implementation agents must not copy MACIOS source files into AgentHub until a future review changes a row to `approved_code_migration` and records:

- license status,
- source commit or checksum,
- module owner,
- acceptance IDs covered,
- contract/smoke tests added,
- security review result,
- data migration impact.

## Migration Rules For Implementation Agents

- Every migration task must cite at least one acceptance ID from A1-A24.
- `approved_pattern_only` means reimplement the idea in AgentHub style; do not copy file contents.
- `review_pending` means read the source for design context only; do not implement from it until reviewed.
- `rejected` means neither code nor architectural shortcut may be used in the mainline.
- Any file containing fake provider output, placeholder URL, dry-run success, demo auto-approval, or in-memory-only product state must be treated as unsafe for direct migration.
- Reference projects under `D:/Public Project/**` may be used to cross-check the pattern, but AgentHub's acceptance tests remain the source of truth.
