# Implementation Scope

## Priority Levels

### P0 Required

P0 is the competition spine and is locked by A1-A12 plus A24:

- IM conversation persistence.
- Message persistence.
- Conversation list sorting, search, archive.
- Conversation members with user, Orchestrator, and multiple agents.
- Mention dispatch.
- Orchestrator planning and dispatch reasons.
- Unified adapter contract across at least two real adapters.
- Artifact store and artifact cards.
- Diff artifact flow.
- Permissioned patch application and artifact versioning.
- Chat-triggered deployment release and deployment cards.
- True SSE event recovery.
- Task traceability across modules.

### P0.5 Required

P0.5 is locked by A13-A17 plus A23:

- Conversation context isolation.
- Pinned key messages in context and task runs.
- Rich card types: code block, file, image, webpage, Diff, deployment.
- User-created custom agents.
- Same-file multi-agent conflict handling.
- Mainstream model provider registry and routing.

### P1 Important

P1 is locked by A18-A22:

- Document range processing with localized patch artifacts.
- Feishu/Lark message, bot card, and cloud-doc connector paths.
- A2A persistent agent mailbox protocol.
- User intervention at task interrupt points.
- Task node redo with lineage.

- Skill registry.
- MCP tools and resources.
- Rich editor controls.
- Human review queue.
- Usage and cost telemetry.
- Context visibility panel.
- Advanced conflict merge UI.
- Feishu event subscriptions and inbound message binding.

### P2 Additional

- PPT rendering.
- Desktop and mobile clients.
- Multi-user real-time collaboration.
- Container runtime pools.
- Advanced long-term memory.
- Cross-machine agent federation.
- Multi-tenant administration.

## Allowed Reference Sources

Implementation agents may study:

- `01-Project_Profiles/**`
- `02-Project_Comparisons/**`
- `03-Knowledge_Extraction/**`
- `04-AI_System_Knowledge/**`
- Source projects under `D:/Public Project/**` listed in the AgentHub engineering plan.

Important acceptance reference files include:

- `D:/Public Project/9router-master/open-sse/config/providers.js`
- `D:/Public Project/9router-master/open-sse/handlers/chatCore.js`
- `D:/Public Project/9router-master/open-sse/translator/response/claude-to-openai.js`
- `D:/Public Project/9router-master/open-sse/translator/response/openai-to-claude.js`
- `D:/Public Project/cline-main/sdk/packages/core/src/extensions/tools/team/multi-agent.ts`
- `D:/Public Project/cline-main/apps/cli/src/runtime/interactive/approvals.ts`
- `D:/Public Project/opencode-dev/packages/opencode/src/session/revert.ts`
- `D:/Public Project/opencode-dev/packages/opencode/src/session/retry.ts`
- `D:/Public Project/opencode-dev/packages/opencode/src/tool/apply_patch.ts`
- `D:/Public Project/ruflo-main/v3/@claude-flow/swarm/src/unified-coordinator.ts`
- `D:/Public Project/cli-main/skills/lark-im/SKILL.md`
- `D:/Public Project/cli-main/skills/lark-im/references/lark-im-messages-send.md`
- `D:/Public Project/openclaw-main/extensions/feishu/src/streaming-card.ts`
- `D:/Public Project/openclaw-main/extensions/feishu/src/pins.ts`
- `D:/Public Project/openclaw-main/extensions/feishu/src/docx.ts`

Implementation agents must not use personal project material as a design source.

## Migration Policy

No legacy module is allowed into the main product unless it satisfies all of:

- Source path is explicitly listed in this file.
- License permits use.
- It passes module boundary review in `docs/module-boundary.md`.
- It is covered by acceptance, contract, or smoke tests.

Current migration allowlist:

- None.

Patterns may be reimplemented from reference projects, but code copying requires explicit license review and source attribution in `docs/implementation-notes.md`.

## Forbidden Mainline Logic

- Hardcoded success.
- Placeholder deployment URLs.
- Adapter outputs created without invoking the configured backend.
- In-memory-only persistence for conversations, messages, tasks, events, or artifacts.
- Silent fallback that hides provider failure.
- Direct write to main workspace by agent adapters.
- Permission bypass for patch application, deployment, shell execution, credential access, or file deletion.
- Cross-conversation context leakage.
- Last-writer-wins for multi-agent same-file changes.
- Provider/model silent fallback.
- Feishu dry-run responses presented as delivered external messages.

## Implementation Task Format

Every implementation task must declare:

```text
Acceptance IDs:
Modules touched:
Reference source files read:
New tests added:
Risk level:
Rollback plan:
```
