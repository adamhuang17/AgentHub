# AgentHub Configuration

AgentHub uses profile-based local configuration. No cloud credential files are
read by default; secrets stay in OS environment variables or local `.env` files.

## Profiles

Supported profiles:

- `demo`
- `test`
- `real`

Profile template files live in `config/`:

- `agenthub.example.env`
- `agenthub.demo.env`
- `agenthub.test.env`
- `agenthub.real.example.env`

These are committed to version control and serve as project-level defaults.

## Load Order

Effective settings are merged in this order, with later entries winning:

1. code defaults
2. `config/agenthub.demo.env`
3. `config/agenthub.{profile}.env`
4. `.env` *(root, auto-loaded)*
5. `AGENTHUB_ENV_FILE` *(explicit override)*
6. OS environment variables *(highest priority)*

### Root `.env`

The project root `.env` file is **automatically loaded** by default. You do not
need to set `AGENTHUB_ENV_FILE=.env`.

- `.env` is for **local, private, real-running configuration** (API keys,
  endpoints, profile selection).
- `.env` is **never committed** to version control (it is in `.gitignore`).
- If `.env` does not exist, no error is raised — the system falls back to
  `config/` profile defaults.
- `config/*.env` files are project-level profile templates that **can** be
  committed.
- `AGENTHUB_ENV_FILE` is only needed for **temporary overrides** beyond `.env`.

### Profile Resolution

The active profile is determined by this priority:

1. **Script parameter** `-Profile xxx` — always wins
2. **OS environment** `AGENTHUB_PROFILE` — wins if no script parameter
3. **`.env` file** `AGENTHUB_PROFILE` — wins if no script parameter and no OS env
4. **Default** `demo` — fallback

**Important:** When you explicitly pass `-Profile demo`, it will **not** be
overridden by `AGENTHUB_PROFILE=real` in `.env`.

### File Types

| File | Purpose | Committed? |
| ------ | --------- | --------- |
| `.env` | Local private config (auto-loaded) | **No** |
| `.env.*` | Local private variants | **No** |
| `config/agenthub.demo.env` | Demo profile defaults | Yes |
| `config/agenthub.test.env` | Test profile defaults | Yes |
| `config/agenthub.example.env` | Example template | Yes |
| `config/agenthub.real.example.env` | Real profile template | Yes |
| `config/agenthub.real.env` | Real profile (secrets) | **No** |
| `config/agenthub.local.env` | Local overrides | **No** |
| `config/agenthub.*.local.env` | Local variant overrides | **No** |
| `config/*.secret.env` | Secret files | **No** |

`AGENTHUB_PROFILE` chooses the profile. `AGENTHUB_ENV` remains the runtime
environment flag used by test-only backends.

## Commands

```powershell
# With explicit profile
.\scripts\agenthub.ps1 doctor -Profile real
.\scripts\agenthub.ps1 api -Profile real
.\scripts\agenthub.ps1 web -Profile real
.\scripts\agenthub.ps1 simulate -Profile real

# Without -Profile: auto-resolves from OS env / .env / default "demo"
.\scripts\agenthub.ps1 doctor
.\scripts\agenthub.ps1 api
```

If your `.env` contains `AGENTHUB_PROFILE=real`, the system automatically uses
the `real` profile without needing `-Profile real` on the command line.

## Runtime Doctor

`GET /api/runtime/doctor` and `scripts/agenthub-doctor.ps1` return only
non-sensitive status:

- `api_status`
- `env_profile`
- `loaded_env_files` *(file paths only, no values)*
- `explicit_env_file_used`
- `db_configured`
- `artifact_store_configured`
- `turn_router_backend`
- `turn_router_configured`
- `agents_enabled_count`
- `agents_configured_count`
- `codex_cli_configured`
- `custom_openai_configured`
- `static_deploy_configured`
- `warnings`

API keys, tokens, and credential values are **never** returned.

The PowerShell doctor also asks the Python diagnostics to check DB, Artifact
Store, and static deployment directory writability without printing secret
values.

## Demo Safety

The `demo` profile does not configure a real router or provider by default.
`simulate` may temporarily use the test TurnRouter in-process when no real router
is configured, and it marks the report with `router_mode="test"`.

Codex CLI runs use the existing read-only CLI adapter path. They do not enable
workspace-write or danger-full-access.
