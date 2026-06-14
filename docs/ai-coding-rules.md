# AI Coding Rules

## Protected Boundaries

The following files are frozen competition boundaries:

- `docs/acceptance-matrix.md`
- `docs/ai-coding-rules.md`
- `tests/acceptance/**`

Implementation agents may read them freely but must not modify them to make implementation easier.

## Required Traceability

Every code change must cite one or more acceptance IDs. A change without an acceptance ID is out of scope.

Valid acceptance IDs are A1-A24 as defined in `docs/acceptance-matrix.md`. A task that does not improve one of those IDs must be rejected or re-scoped before implementation.

Commit or task notes must include:

```text
Acceptance IDs:
Files changed:
Reference files read:
Verification run:
Known residual risk:
```

## No Fake Success

Forbidden:

- Hardcoded success responses.
- Placeholder URLs presented as deployed releases.
- Returning `succeeded` when provider credentials are missing.
- Falling back to static text while pretending an agent ran.
- Creating artifact cards without artifact records.
- Applying patches without review.
- Cross-conversation context reuse.
- Last-writer-wins conflict handling for multi-agent edits.
- Provider/model fallback presented as intentional routing.
- Feishu/Lark dry-run or local-only card presented as delivered external message.
- REST event replay presented as SSE recovery without opening `text/event-stream`.

Required:

- External dependency failure must return `failed`, `provider_not_configured`, `credential_invalid`, `timeout`, or a similarly explicit error.
- Error payloads must include `error_code`, `message`, `provider` when relevant, and `recovery_hint`.

## Adapter Rules

- Adapter-specific fields must not leak into Orchestrator.
- All adapters accept `AgentRunRequest`.
- All adapters emit `AgentRunEvent`.
- All file changes must land in run workspace first.
- Agent output must be normalized before entering Artifact Store.
- Agent-to-Agent communication must use the A2A envelope and mailbox protocol.
- User interventions must be persisted and applied at interrupt points.

## Persistence Rules

- Conversation, message, task, step, event, artifact, deployment, review, and audit state must be durable.
- Pins, context bundles, A2A messages, intervention records, task lineage, provider routing decisions, Feishu delivery ledgers, and trace records must be durable.
- In-memory state may be used only as cache.
- Cache loss must not lose product state.

## Test Rules

- Acceptance tests define product behavior.
- Contract tests define schemas and module boundaries.
- Smoke tests define boot and environment checks.
- Integration tests verify local reference source paths and external connector readiness.
- Implementation agents may add contract and smoke tests.
- Implementation agents must not weaken acceptance tests.

## Reference Rules

Use local open-source reference paths listed in the engineering plan. Do not use personal project material as design evidence.
