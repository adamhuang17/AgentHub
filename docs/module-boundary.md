# Module Boundary

## Boundary Rule

Modules may depend inward on shared types and infrastructure, but must not bypass another module's public service API.

## Modules

| Module | Owns | May Call | Must Not Do |
| --- | --- | --- | --- |
| `conversations` | conversation, message, member, pin, summary | `memory`, `execution` read APIs | execute agents, write artifacts directly |
| `agents` | profiles, adapters, adapter health | `permissions`, `execution` events | mutate main workspace directly |
| `orchestration` | task, plan, step, dispatch | `agents`, `execution`, `memory` | store artifact content |
| `execution` | queue, worker, events, heartbeats | `agents`, `artifacts`, `permissions` | decide product routing policy |
| `artifacts` | artifact metadata, versions, diffs, patch apply | `permissions`, storage integrations | call LLMs or agent adapters |
| `preview` | preview sessions, preview URLs | `artifacts` | mark deployment success |
| `deployment` | release records and provider calls | `artifacts`, `permissions`, credentials | fabricate published URLs |
| `permissions` | review requests, decisions, audit logs | credentials | apply patches or deploy directly |
| `memory` | context bundles, summaries, retrieval | `conversations`, `artifacts` read APIs | execute tasks |
| `mcp` | tools/resources protocol | public services only | bypass permissions |
| `a2a` | agent mailbox envelopes, delivery state, correlation IDs | `conversations`, `agents`, `execution` events | pass agent messages only through prompts |
| `interventions` | user supplemental context, corrections, interrupt-point state | `orchestration`, `execution` events | abort running steps as the only steering mechanism |
| `documents` | range selectors, document patch planning, range validation | `artifacts`, `permissions` | rewrite full documents when a range is selected |
| `integrations.feishu` | Feishu/Lark credentials, message send, bot cards, cloud-doc calls | `permissions`, `artifacts`, credentials | claim dry-run or local card as external delivery |
| `model_router` | provider registry, model resolution, request format selection | credentials, `agents` read APIs | silently fall back to another provider/model |
| `trace` | cross-module trace records and audit views | all public module event APIs | scrape debug logs as product trace |

## Persistence Ownership

- Only `conversations` writes conversation and message tables.
- Only `orchestration` writes task, plan, and step tables.
- Only `execution` writes execution events and run heartbeats.
- Only `artifacts` writes artifact and artifact version tables.
- Only `deployment` writes deployment release tables.
- Only `permissions` writes review and audit tables.
- Only `a2a` writes agent mailbox envelope tables.
- Only `interventions` writes intervention tables.
- Only `integrations.feishu` writes external delivery ledger records.
- Only `model_router` writes provider health/cache records.
- Only `trace` writes trace projection tables.

## Workspace Safety

Agent adapters write only to run workspaces. The main workspace changes only through `artifacts.apply_service`, after permission and version checks.

Parallel agent edits to the same artifact path must produce Diff artifacts and conflict records. The main artifact version must not change until conflict resolution and permission checks complete.

## Import Discipline

Implementation agents must keep module imports acyclic. Shared event schemas and API DTOs belong in `packages/shared` or `services/api/app/shared`.
