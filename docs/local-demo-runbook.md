# Pre-Lark Local Product Demo Runbook

This runbook starts AgentHub as a local product demo without Feishu/Lark, MCP,
self-created agents, cloud deployment, workspace-write, Codex danger mode, or
Claude write tools.

## Quick Start with `.env`

1. Create `.env` in the project root:

```bash
# .env — local private config (never committed)
AGENTHUB_PROFILE=real
AGENTHUB_TURN_ROUTER_BACKEND=openai_compatible
AGENTHUB_TURN_ROUTER_BASE_URL=https://your-router.example/v1
AGENTHUB_TURN_ROUTER_API_KEY=sk-your-key
AGENTHUB_TURN_ROUTER_MODEL=your-model
```

1. Run commands — `.env` is auto-loaded:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\agenthub.ps1 doctor -Profile real
powershell -ExecutionPolicy Bypass -File .\scripts\agenthub.ps1 api -Profile real
powershell -ExecutionPolicy Bypass -File .\scripts\agenthub.ps1 web -Profile real
powershell -ExecutionPolicy Bypass -File .\scripts\agenthub.ps1 simulate -Profile real
```

If your `.env` contains `AGENTHUB_PROFILE=real`, you can omit `-Profile`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\agenthub.ps1 doctor
powershell -ExecutionPolicy Bypass -File .\scripts\agenthub.ps1 api
powershell -ExecutionPolicy Bypass -File .\scripts\agenthub.ps1 simulate
```

No need to set `$env:AGENTHUB_ENV_FILE=".env"` — it's automatic.

## Unified Commands

Use the profile entrypoint instead of hand-setting environment variables:

```powershell
.\scripts\agenthub.ps1 doctor -Profile demo
.\scripts\agenthub.ps1 api -Profile demo
.\scripts\agenthub.ps1 web -Profile demo
.\scripts\agenthub.ps1 simulate -Profile demo
```

Use `NO_PROXY=127.0.0.1,localhost` for local HTTP tests when a machine-wide
proxy is configured.

## API

```powershell
.\scripts\agenthub.ps1 api -Profile demo
```

## Web

```powershell
.\scripts\agenthub.ps1 web -Profile demo
```

Open `http://127.0.0.1:3000`.

The first screen is the local IM product surface:

- conversation list, defaulting to the latest active conversation
- new conversation form with `single` or `group` mode
- Agent panel from `GET /api/agents`
- message composer with optional `@Agent`
- persisted message stream with artifact, diff, review, deployment, preview,
  download, and pin actions
- Timeline from `GET /api/conversations/{id}/events`
- Context Panel from `GET /api/conversations/{id}/context`
- local demo status from `/health`

The UI does not require manual `conversation_id` or `test_run_id` entry.

## Simulation

```powershell
.\scripts\agenthub.ps1 simulate -Profile demo
```

The simulation creates real local conversations and events:

- model provider direct response: failed when provider env is missing, succeeded
  only if the configured provider returns a real assistant message
- Codex complex task: blocked when Codex CLI is missing; if configured, creates a
  planned-step AgentRun and records the real adapter result
- blocked capability task: creates a blocked step and no fake AgentRun
- context/pin case: pins a message and a local artifact, builds context, and
  starts a direct-response run with the real context summary

No fake assistant message, fake Artifact, fake Deployment URL, or fake success is
created by the simulation.

## Verification

```powershell
python -B -m pytest tests/contract/test_settings_loader.py tests/contract/test_runtime_doctor.py tests/contract/test_context_builder.py tests/contract/test_pinned_context.py -q
python -B -m pytest tests/acceptance/test_core_context_pin.py tests/acceptance/test_product_local_demo_flow.py tests/acceptance/test_core_execution_trace.py tests/acceptance/test_local_simulation_flow.py -q
node --test apps/web/app.test.mjs
git diff --check
```

For acceptance tests, start the API and tests in the same shell command or keep
the API process open in a separate terminal. In this environment, detached
helper processes may be cleaned up after a tool command exits.
