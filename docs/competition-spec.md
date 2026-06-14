# AgentHub Competition Spec

## Product Goal

AgentHub is a production-oriented IM-first multi-agent collaboration platform. Users create conversations, mention or select agents, ask for product work, and receive durable artifacts such as code, documents, diffs, previews, files, and deployment releases.

The product must support this chain:

```text
IM conversation
  -> Orchestrator plan
  -> Agent adapter execution
  -> A2A collaboration and user intervention
  -> Artifact store
  -> Diff and versioning
  -> Permissioned apply
  -> Deployment release
  -> Event recovery
  -> Trace and audit
```

## P0 Scope

P0 is locked by `docs/acceptance-matrix.md` A1-A12 and A24. No implementation task may be considered complete unless it maps to at least one acceptance ID.

P0 capabilities:

- Persistent IM conversations and messages.
- Conversation list search, archive, and last-active ordering.
- Conversation members including user, Orchestrator, and multiple agents.
- Mention-based agent dispatch.
- Orchestrator plan and step dispatch when no agent is mentioned.
- Unified `AgentRunRequest` accepted by at least two real adapters.
- Artifact store with artifact cards in the message stream.
- Diff artifact flow that does not overwrite the main workspace before approval.
- Permissioned patch application with new artifact versions.
- Chat-triggered deployment release with real URL on success and explicit error on failure.
- Event replay and recovery across browser refresh, worker restart, and true SSE reconnect.
- Task traceability.

## P0.5 Scope

- Conversation context isolation and pinned key messages.
- Rich cards for code, files, images, webpages, Diffs, and deployments.
- User-created agents.
- Multi-agent same-file conflict handling.
- Document range processing.
- Mainstream model provider routing.

## P1 Scope

- MCP server exposing tools and artifact resources.
- Rich code editor and multi-file diff review.
- Cost, token, latency, and adapter health telemetry.
- Human review queue with comments and audit export.
- Feishu/Lark connector paths for messages, bot cards, and cloud-doc ranges.
- A2A agent mailbox protocol.
- User interventions at interrupt points.
- Task node redo and lineage.

## P2 Scope

- PPT browsing and revision.
- Desktop and mobile clients.
- Multi-user collaborative editing.
- Containerized runtime pools for agent execution.
- Cross-workspace agent federation.
- Advanced memory extraction and retrieval.

## Non-Negotiable Rules

- No hardcoded success.
- No fake deployment URL.
- No silent fallback that presents failure as success.
- No direct file overwrite by an agent adapter.
- No high-risk action without permission decision and audit event.
- No implementation outside the module boundary defined in `docs/module-boundary.md`.
- No cross-conversation context leakage.
- No last-writer-wins conflict resolution for multi-agent code changes.
