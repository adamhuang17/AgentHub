# AgentHub Lite Migration Plan

> Status: source inventory only. This document does not claim that AgentHub Lite features are implemented.

## Scope

This pass inventories two source trees:

- OpenCode source: `../opencode-dev`
- Legacy AgentHub source: `.`

No business code was changed, no directories were moved, and no existing code was deleted. Later implementation must build the AgentHub Lite frontend on OpenCode `packages/app`; legacy `apps/web` is inventory-only and must not be reused as the product UI.

## Non-negotiable Rules

- No fake success: unavailable external services, missing API keys, missing CLIs, unreachable OpenCode service, adapter failures, and deployment failures must return explicit failure state and `error_code`.
- No hardcoded demo results: do not hardcode Agent replies, artifact contents, deployment URLs, run success, or Orchestrator plans as real output.
- Demo seed data is allowed only when named `demo_seed` and must be visibly separated from real execution results in UI and API responses.
- Legacy AgentHub Web under `apps/web` is deprecated for AgentHub Lite. Do not copy or extend `apps/web/app.js`.
- Prefer OpenCode runtime capabilities for sessions, message streaming, diffs, file panels, composer, permissions, and SDK/API access.

## Reuse

### OpenCode Frontend

The AgentHub Lite page should be added inside `../opencode-dev/packages/app`, reusing the existing Solid app shell, providers, routing, styling, and `@opencode-ai/ui` components.

- `packages/app/src/app.tsx`
  - Existing route tree, provider stack, server health gate, QueryClient, theme/i18n/dialog providers.
  - Future `/agenthub` route should be added here or through the same routing pattern.
- `packages/app/src/pages/home.tsx`
  - Reusable patterns for server/project/session list loading, search, empty/loading states, OpenCode v2 theme tokens, and list row styling.
  - Do not reuse it as an AgentHub page wholesale; use it as UI and data-flow reference.
- `packages/app/src/pages/session.tsx`
  - Reusable workspace/session layout ideas: center conversation area, docked composer, side panel, review panel, file tree, diff loading, error toast handling.
  - `SessionComposerRegion` and related prompt submit flow are strong references for later AgentHub input design.
- `packages/app/src/pages/session/message-timeline.tsx`
  - Reusable message timeline, assistant/user turn rendering, virtualized rows, error card pattern, diff summary row, and `DiffChanges`/file diff rendering.
  - AgentHub-specific message cards should be separate components, but should follow this rendering model.
- `packages/app/src/pages/session/session-side-panel.tsx`
  - Reusable right-side panel pattern for files, changes, tabs, resize handle, and diff-focused navigation.
  - AgentHub right panel can adapt the same shell for Agent roster plus artifact preview.
- `packages/app/src/components/prompt-input` and `packages/app/src/pages/session/composer`
  - Reusable composer architecture, attachments/context parts, submit flow, queued follow-up ideas, and failure handling patterns.
- `packages/app/src/components/file-tree.tsx`, `packages/app/src/pages/session/review-tab.tsx`, `packages/app/src/utils/diffs.ts`
  - Reusable file/diff display utilities for later `DiffCard`.
- `packages/ui`
  - Reusable primitives: `Button`, `ButtonV2`, `IconButton`, `Card`, `Tabs`, `ScrollView`, `ResizeHandle`, `Dialog`, `DropdownMenu`, `Tooltip`, `TextField`, `Spinner`, `Markdown`, `File`, `DiffChanges`, `message-part`, theme tokens, Tailwind utilities.

### OpenCode HTTP/SDK APIs

OpenCode exposes two related API surfaces. Later implementation must verify the chosen surface against a running OpenCode service instead of assuming compatibility.

V2 server API in `../opencode-dev/packages/server/src`:

- Health:
  - `GET /api/health`
- Session:
  - `GET /api/session`
  - `POST /api/session`
  - `GET /api/session/:sessionID`
  - `POST /api/session/:sessionID/prompt`
  - `POST /api/session/:sessionID/compact`
  - `POST /api/session/:sessionID/wait`
  - `GET /api/session/:sessionID/context`
- Messages:
  - `GET /api/session/:sessionID/message`
- Permissions:
  - `GET /api/permission/request`
  - `GET /api/permission/saved`
  - `DELETE /api/permission/saved/:id`
  - `GET /api/session/:sessionID/permission`
  - `POST /api/session/:sessionID/permission/:requestID/reply`
- Filesystem:
  - `GET /api/fs/read/*`
  - `GET /api/fs/list`
  - `GET /api/fs/find`

Current app/instance API in `../opencode-dev/packages/opencode/src/server/routes/instance/httpapi/groups`:

- Session:
  - `GET /session`
  - `POST /session`
  - `GET /session/:sessionID`
  - `GET /session/:sessionID/message`
  - `POST /session/:sessionID/message`
  - `POST /session/:sessionID/prompt_async`
  - `GET /session/:sessionID/diff`
  - `POST /session/:sessionID/abort`
  - `POST /session/:sessionID/revert`
  - `POST /session/:sessionID/unrevert`
- Permission:
  - `GET /permission`
  - `POST /permission/:requestID/reply`
  - Deprecated session-scoped respond endpoint exists at `POST /session/:sessionID/permissions/:permissionID`.
- File:
  - `GET /file`
  - `GET /file/content`
  - `GET /file/status`
  - `GET /find`
  - `GET /find/file`
  - `GET /find/symbol`
- VCS diff:
  - `GET /vcs/diff`
  - `GET /vcs/diff/raw`

OpenCode app-side access patterns:

- `packages/app/src/context/server-sdk.tsx` creates SDK clients per server and directory, and maintains global event streams.
- `packages/app/src/context/directory-sync.ts` loads sessions, messages, diffs, todos, and session lists.
- `packages/app/src/context/file.tsx` uses `client.file.list` and `client.file.content`.
- `packages/app/src/context/permission.tsx` uses `client.permission.respond` and session permission APIs.
- `packages/app/src/components/prompt-input/submit.ts` creates sessions and sends prompts through the OpenCode SDK.

## Migrate

### Legacy AgentHub Control Plane

The following backend modules are good migration sources for AgentHub Lite, because they already model product concepts required by the competition:

- `services/api/app/main.py`
  - Existing HTTP dispatcher and health endpoint.
  - Current health: `GET /health`.
  - Existing runtime doctor: `GET /api/runtime/doctor`.
- `services/api/app/conversations`
  - Existing endpoints:
    - `GET /api/conversations`
    - `POST /api/conversations`
    - `GET /api/conversations/{id}`
    - `POST /api/conversations/{id}/archive`
    - `GET /api/conversations/{id}/messages`
    - `POST /api/conversations/{id}/messages`
    - `GET /api/conversations/{id}/members`
    - `GET /api/conversations/{id}/context`
    - `GET /api/conversations/{id}/events`
    - `POST /api/conversations/{id}/pin`
    - `POST /api/conversations/{id}/tasks`
  - Reuse message persistence, mentions payloads, references, members, conversation events, and failure cards.
  - Migration gap: current modes include legacy names such as `group_agent`/`private_agent`; Lite requirement wants `single`/`group`.
- `services/api/app/agents`
  - Reuse `routes.py`, `repository.py`, `runtime_status.py`, `provider_config.py`, `adapter_health.py`, and `adapter_registry.py`.
  - Existing endpoints:
    - `GET /api/agents`
    - `GET /api/adapters`
    - `GET /api/agents/{id}/adapter-health`
  - Reuse adapter health contract with `configured`, `status`, `error_code`, `recovery_hint`, and `capabilities`.
- `services/api/app/agents/adapters`
  - Reuse `base.py` protocol and existing real/failing adapters:
    - `custom_openai.py`
    - `codex_cli.py`
    - `claude_code_cli.py`
    - `disabled.py`
    - parser modules under `parsers/`
  - Add a new `opencode_http` adapter later, but do not fake OpenCode output if the OpenCode server is unavailable.
- `services/api/app/agent_runs`
  - Reuse AgentRun schema, repository, service, routes, event persistence, and explicit failure handling.
  - Existing endpoints:
    - `POST /api/runs`
    - `GET /api/runs/{id}`
    - `GET /api/runs/{id}/events`
    - `GET /api/agent-runs/{id}/events`
  - Current `EVENT_TYPES` does not include every later requested event, such as `artifact_created`; extend the schema before emitting new events.
- `services/api/app/artifacts`
  - Reuse artifact repository, store, diff service, patch service, review repository, schema validation, content/download routes, and diff artifacts.
  - Existing endpoints:
    - `GET /api/artifacts`
    - `POST /api/artifacts`
    - `GET /api/artifacts/{id}`
    - `GET /api/artifacts/{id}/versions`
    - `GET /api/artifacts/{id}/content`
    - `GET /api/artifacts/{id}/download`
    - `GET /api/artifacts/{id}/diff`
    - `POST /api/artifacts/diff`
    - `POST /api/artifacts/{id}/apply-patch`
    - `GET /api/review-requests`
    - `POST /api/review-requests/{id}/decision`
  - Migration gap: Lite requires `code_file`, `markdown_doc`, `web_preview`, `source_diff`, and `deployment_release`; current schema supports some diff concepts but still needs type alignment.
- `services/api/app/preview`
  - Reuse as the backend boundary for artifact preview, but verify exact preview endpoints during implementation.
- `services/api/app/deployment`
  - Reuse release schema, repository, service, routes, and `providers/static_host.py`.
  - Existing endpoints:
    - `GET /api/deployments`
    - `GET /api/deployments/{id}`
    - `POST /api/artifacts/{id}/deploy`
    - static serving under `/static-deployments/{release_id}/...`
  - Migration gap: `static_host` validates artifact type, configured directory, read/write, path safety, and checksum. Later requirement also asks that the returned URL is reachable; add a real reachability check before marking `published`.
- `services/api/app/orchestration`
  - Reuse TurnDecision validation idea, `planner.py`, `capability_matcher.py`, `mention_dispatcher.py`, task repository, planner trace, and configured backend gateway.
  - Migration gap: requested Lite schema uses `steps[].id`, `title`, `instruction`, and `kind` including `deploy`; current schema uses `objective`, lacks step `id/title/instruction`, and only allows `analysis/implementation/review`.
  - Migration risk: `conversations/routes.py` currently contains `_promote_explicit_planning_request`, which can synthesize a fixed three-step plan based on keyword markers. That must not be carried into Lite as real Orchestrator behavior.
- `services/api/app/memory`
  - Reuse `context_builder.py`, `pinned_context.py`, `prompt_context.py`, and schema as the conversation/task context source.
- `services/api/app/permissions`
  - Reuse audit schema and repository concepts. For Lite, permissions must be connected to OpenCode permission requests and artifact/diff apply gates.
- `services/api/app/shared`
  - Reuse database, settings, environment loading, error objects, HTTP helpers, runtime diagnostics, and time helpers.

## Discard

- `apps/web`
  - Discard as product frontend for AgentHub Lite.
  - Do not copy, extend, or route users to `apps/web/app.js`, `apps/web/index.html`, or `apps/web/server.mjs`.
  - It may remain in the repository as legacy reference until explicitly removed in a later cleanup phase, but it must not be the basis of `/agenthub`.
- Fixed Orchestrator/demo behavior that looks like real execution:
  - Do not use fixed three-step planner output as real planner output.
  - Do not use local placeholder agents as real `GET /api/agents` results.
  - Do not use static text as an Agent reply.
  - Do not use static URLs as deployment output.
- Any fallback path that turns an unavailable backend into a success state:
  - Missing CLI must remain failed.
  - Missing API key must remain failed.
  - OpenCode unreachable must remain failed.
  - Deployment copy or URL verification failure must remain failed.

## Defer

These are later phases and are not completed by this inventory document:

- Add OpenCode `packages/app` route `/agenthub`.
- Add AgentHub frontend components: `AgentHubShell`, `ConversationList`, `AgentRoster`, `RoomHeader`, `AgentMentionPicker`, `OrchestratorPlanCard`, `AgentRunCard`, `ArtifactCard`, `DiffCard`, `DeploymentCard`, and `CreateAgentDialog`.
- Add `packages/app/src/agenthub/api/agenthub-client.ts` and `packages/app/src/agenthub/types.ts`.
- Wire the AgentHub page to real Control Plane APIs.
- Add `services/api/app/agents/adapters/opencode_http.py`.
- Implement the Lite Orchestrator schema requested by the competition.
- Normalize conversation modes to `single` and `group`.
- Implement full group chat and `@Agent` dispatch behavior for Lite.
- Implement artifact discovery from real OpenCode diffs and workspace files.
- Implement web preview, markdown preview, code preview, and deployment cards in OpenCode UI.
- Implement user-created Agent persistence and custom OpenAI execution flow in the Lite UI.
- Refresh final competition docs and demo script after the actual implementation lands.

## Key Risks

- API surface mismatch: OpenCode has current instance routes and newer `/api/...` v2 routes. The adapter must choose one surface and verify it against a running OpenCode service.
- Runtime availability: OpenCode server, Codex CLI, Claude Code CLI, and model-provider keys are external dependencies. UI and API must expose explicit failure states.
- Schema mismatch: current AgentHub TurnDecision and conversation modes do not exactly match Lite requirements.
- Fake plan risk: existing fixed plan promotion in legacy conversation routing violates the Lite rule if used as real planner output.
- Artifact type mismatch: current artifact schema needs explicit alignment with Lite artifact types.
- Deployment verification gap: current static host copy/checksum flow should be extended with real URL accessibility validation before `published`.
- UI reuse boundary: OpenCode UI should be reused, but legacy `apps/web` must not be used for new product UI.

## Next Phase Recommendation

1. Add a minimal `/agenthub` route in `packages/app` with static but clearly labeled empty states: `not_connected`, `waiting_for_backend`, and `no_runtime_result`.
2. Add the real AgentHub API client with no local fake-data fallback. Closed backend must display `api_unreachable` and disable send.
3. Add the OpenCode HTTP adapter in legacy backend. Health must return `opencode_server_unavailable` until a real OpenCode service responds.
4. Replace legacy planner schema with the requested Lite schema and remove keyword/fixed-plan fallback from real routing.
5. Extend artifact and deployment contracts, then connect UI cards only to real backend data.

## Verification Notes

Suggested commands for this inventory phase:

```powershell
Test-Path docs\agenthub-lite-migration-plan.md
git diff -- docs\agenthub-lite-migration-plan.md
```

Suggested commands for later implementation phases:

```powershell
bun --cwd ..\opencode-dev\packages\app dev
python -m services.api.app.main
python -m pytest
```

This document intentionally does not claim any AgentHub Lite runtime feature has been completed.
