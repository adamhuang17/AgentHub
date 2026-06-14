from __future__ import annotations

import json

from services.api.app.agents.runtime_status import runtime_status_for_agent
from services.api.app.shared.database import connect
from services.api.app.shared.settings import Settings, get_settings
from services.api.app.shared.time import utc_now


MODEL_AGENT_ID = "agent-demo-model"
CODEX_AGENT_ID = "agent-codex-profile"
CLAUDE_AGENT_ID = "agent-claude-profile"


def ensure_demo_agents(settings: Settings | None = None) -> dict[str, dict[str, object]]:
    active = settings or get_settings()
    model_status = runtime_status_for_agent({"id": MODEL_AGENT_ID, "provider": active.model_agent_provider})
    codex_status = runtime_status_for_agent({"id": CODEX_AGENT_ID, "provider": "codex"})
    claude_status = runtime_status_for_agent({"id": CLAUDE_AGENT_ID, "provider": "anthropic"})
    now = utc_now()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO agents (
                id, name, provider, avatar, initials, capability_tags_json,
                execution_enabled, configured, health_status,
                enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, NULL, 'AI', ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                provider = excluded.provider,
                capability_tags_json = excluded.capability_tags_json,
                execution_enabled = excluded.execution_enabled,
                configured = excluded.configured,
                health_status = excluded.health_status,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (
                MODEL_AGENT_ID,
                "Demo Model Agent",
                active.model_agent_provider,
                json.dumps(["direct_response", "chat", "model"], separators=(",", ":")),
                1 if model_status.execution_enabled else 0,
                1 if model_status.configured else 0,
                model_status.health_status,
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO agents (
                id, name, provider, avatar, initials, capability_tags_json,
                execution_enabled, configured, health_status,
                enabled, created_at, updated_at
            )
            VALUES (?, 'Codex Profile', 'codex', NULL, 'CP', ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                capability_tags_json = excluded.capability_tags_json,
                execution_enabled = excluded.execution_enabled,
                configured = excluded.configured,
                health_status = excluded.health_status,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (
                CODEX_AGENT_ID,
                json.dumps(["implementation", "code", "review", "workspace"], separators=(",", ":")),
                1 if codex_status.execution_enabled else 0,
                1 if codex_status.configured else 0,
                codex_status.health_status,
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO agents (
                id, name, provider, avatar, initials, capability_tags_json,
                execution_enabled, configured, health_status,
                enabled, created_at, updated_at
            )
            VALUES (?, 'Claude Code Profile', 'anthropic', NULL, 'CC', ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                capability_tags_json = excluded.capability_tags_json,
                execution_enabled = excluded.execution_enabled,
                configured = excluded.configured,
                health_status = excluded.health_status,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (
                CLAUDE_AGENT_ID,
                json.dumps(["code", "reasoning", "documents"], separators=(",", ":")),
                1 if claude_status.execution_enabled else 0,
                1 if claude_status.configured else 0,
                claude_status.health_status,
                now,
                now,
            ),
        )
    return {
        "model": {
            "id": MODEL_AGENT_ID,
            "provider": active.model_agent_provider,
            "configured": model_status.configured,
        },
        "codex": {
            "id": CODEX_AGENT_ID,
            "provider": "codex",
            "configured": codex_status.configured,
        },
        "claude": {
            "id": CLAUDE_AGENT_ID,
            "provider": "anthropic",
            "configured": claude_status.configured,
        },
    }
