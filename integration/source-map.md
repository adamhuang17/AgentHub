# Source Map

| Final path | Source | Competition role |
| --- | --- | --- |
| `services/api` | old AgentHub `services/api` | Control Plane API, Agent registry, Orchestrator, AgentRun, Artifact, Preview, Deploy |
| `apps/web` | modified OpenCode `opencode-dev` | Web UI, `/agenthub` page, OpenCode runtime and HTTP service |
| `docs`, `integration`, `scripts` | AgentHub-Lite scheme A + curated docs | final product entry, running guide, no fake success policy |

Deleted from final package:

- old AgentHub `apps/web`
- repository metadata and CI
- runtime caches and local sqlite files
- unrelated OpenCode desktop/enterprise/statistics/storybook/container packages
