from __future__ import annotations

import json
import uuid
from sqlite3 import Row

from services.api.app.agents.adapter_health import AdapterHealth
from services.api.app.agents.adapters.custom_openai import CustomOpenAIAdapter
from services.api.app.agents.provider_config import ProviderConfig, credential_value_from_environment, provider_config_from_agent
from services.api.app.agents.runtime_status import enrich_agent_runtime
from services.api.app.shared.database import connect
from services.api.app.shared.errors import ValidationError
from services.api.app.shared.settings import get_settings
from services.api.app.shared.time import utc_now


def list_agents(enabled: bool | None = None, kind: str | None = None) -> list[dict[str, object]]:
    return [enrich_agent_runtime(agent) for agent in list_agent_profiles(enabled=enabled, kind=kind)]


def list_agent_profiles(enabled: bool | None = None, kind: str | None = None) -> list[dict[str, object]]:
    query = "SELECT * FROM agents"
    params: list[object] = []
    clauses = ["(kind IS NULL OR kind != 'deleted')"]
    if enabled is not None:
        clauses.append("enabled = ?")
        params.append(1 if enabled else 0)
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY name ASC"

    with connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [_agent_from_row(row) for row in rows]


def create_agent_profile(raw: dict[str, object]) -> dict[str, object]:
    name = _required_string(raw.get("name"), "name")
    capability_tags = _string_list(raw.get("capability_tags"), "capability_tags")
    system_prompt = _optional_string(raw.get("system_prompt"), "system_prompt")
    provider = _provider_from_body(raw)
    adapter_kind = _adapter_kind_from_body(raw, provider)
    model = _model_from_body(raw)
    avatar = _optional_string(raw.get("avatar"), "avatar") or _optional_string(raw.get("avatar_url"), "avatar_url")
    enabled = raw.get("enabled") if isinstance(raw.get("enabled"), bool) else True
    allowed_tools = _string_list(raw.get("allowed_tools"), "allowed_tools")
    agent_id = _optional_string(raw.get("id"), "id") or f"agent_{uuid.uuid4().hex}"
    api_base = _optional_string(raw.get("api_base"), "api_base")
    executable_path = _optional_string(raw.get("executable_path"), "executable_path")
    api_key = _optional_secret(raw.get("api_key"), "api_key")
    kind = _kind_from_body(raw, provider, adapter_kind)
    credential_source = (
        _credential_source_for_agent(agent_id)
        if api_key
        else _optional_string(raw.get("credential_source"), "credential_source")
    )
    configured = False
    execution_enabled = False
    health_status = "profile_only"
    if _connection_test_required(raw):
        health = _connection_test(
            agent_id=agent_id,
            provider=provider,
            adapter_kind=adapter_kind,
            api_base=api_base,
            model=model,
            api_key=api_key,
            executable_path=executable_path,
        )
        configured = health.configured
        execution_enabled = health.configured
        health_status = health.status
    now = utc_now()

    with connect() as connection:
        connection.execute(
            """
            INSERT INTO agents (
                id, name, provider, avatar, avatar_url, initials, capability_tags_json,
                adapter_kind, system_prompt, model, api_base, credential_source, kind,
                executable_path, allowed_tools_json, execution_enabled, configured, health_status,
                enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                name,
                provider,
                avatar,
                avatar,
                _initials(name),
                json.dumps(capability_tags, ensure_ascii=False, separators=(",", ":")),
                adapter_kind,
                system_prompt,
                model,
                api_base,
                credential_source,
                kind,
                executable_path,
                json.dumps(allowed_tools, ensure_ascii=False, separators=(",", ":")),
                1 if execution_enabled else 0,
                1 if configured else 0,
                health_status,
                1 if enabled else 0,
                now,
                now,
            ),
        )
        if api_key:
            _store_agent_secret(connection, agent_id=agent_id, secret_name="api_key", secret_value=api_key, now=now)
    return get_agents_by_ids([agent_id])[0]


def update_agent_profile(agent_id: str, raw: dict[str, object]) -> dict[str, object]:
    current = _get_agent_profile_row(agent_id)
    next_provider = _provider_from_body(raw) if ("provider" in raw or "model" in raw) else str(current.get("provider") or "")
    next_adapter_kind = (
        _adapter_kind_from_body(raw, next_provider)
        if ("provider" in raw or "model" in raw or "adapter_kind" in raw)
        else str(current.get("adapter_kind") or _adapter_kind_from_body({}, next_provider))
    )
    next_model = _model_from_body(raw) if "model" in raw else _optional_string(current.get("model"), "model")
    next_api_base = _optional_string(raw.get("api_base"), "api_base") if "api_base" in raw else _optional_string(current.get("api_base"), "api_base")
    next_executable_path = (
        _optional_string(raw.get("executable_path"), "executable_path")
        if "executable_path" in raw
        else _optional_string(current.get("executable_path"), "executable_path")
    )
    api_key = _optional_secret(raw.get("api_key"), "api_key") if "api_key" in raw else None

    updates: list[str] = []
    params: list[object] = []
    if "name" in raw:
        name = _required_string(raw.get("name"), "name")
        updates.extend(["name = ?", "initials = ?"])
        params.extend([name, _initials(name)])
    if "avatar" in raw or "avatar_url" in raw:
        avatar = _optional_string(raw.get("avatar"), "avatar") or _optional_string(raw.get("avatar_url"), "avatar_url")
        updates.extend(["avatar = ?", "avatar_url = ?"])
        params.extend([avatar, avatar])
    if "capability_tags" in raw:
        updates.append("capability_tags_json = ?")
        params.append(json.dumps(_string_list(raw.get("capability_tags"), "capability_tags"), ensure_ascii=False, separators=(",", ":")))
    if "system_prompt" in raw:
        updates.append("system_prompt = ?")
        params.append(_optional_string(raw.get("system_prompt"), "system_prompt"))
    if "provider" in raw or "model" in raw:
        updates.extend(["provider = ?", "adapter_kind = ?"])
        params.extend([next_provider, next_adapter_kind])
    if "model" in raw:
        updates.append("model = ?")
        params.append(next_model)
    if "api_base" in raw:
        updates.append("api_base = ?")
        params.append(next_api_base)
    if "credential_source" in raw:
        updates.append("credential_source = ?")
        params.append(_optional_string(raw.get("credential_source"), "credential_source"))
    if api_key:
        updates.append("credential_source = ?")
        params.append(_credential_source_for_agent(agent_id))
    if "executable_path" in raw:
        updates.append("executable_path = ?")
        params.append(next_executable_path)
    if "kind" in raw or "agent_type" in raw:
        updates.append("kind = ?")
        params.append(_kind_from_body(raw, next_provider, next_adapter_kind))
    if "allowed_tools" in raw:
        updates.append("allowed_tools_json = ?")
        params.append(json.dumps(_string_list(raw.get("allowed_tools"), "allowed_tools"), ensure_ascii=False, separators=(",", ":")))
    if "enabled" in raw:
        updates.append("enabled = ?")
        params.append(1 if raw.get("enabled") is True else 0)
    if _connection_test_required(raw):
        health = _connection_test(
            agent_id=agent_id,
            provider=next_provider,
            adapter_kind=next_adapter_kind,
            api_base=next_api_base,
            model=next_model,
            api_key=api_key or _existing_api_key(agent_id),
            executable_path=next_executable_path,
        )
        updates.extend(["configured = ?", "execution_enabled = ?", "health_status = ?"])
        params.extend([1 if health.configured else 0, 1 if health.configured else 0, health.status])
    if not updates:
        return get_agents_by_ids([agent_id])[0]
    updates.append("updated_at = ?")
    now = utc_now()
    params.append(now)
    params.append(agent_id)
    with connect() as connection:
        cursor = connection.execute(
            f"UPDATE agents SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        if cursor.rowcount == 0:
            raise ValidationError("Agent not found.", code="agent_not_found")
        if api_key:
            _store_agent_secret(connection, agent_id=agent_id, secret_name="api_key", secret_value=api_key, now=now)
    return get_agents_by_ids([agent_id])[0]


def delete_agent_profile(agent_id: str) -> dict[str, object]:
    now = utc_now()
    with connect() as connection:
        row = connection.execute(
            "SELECT id FROM agents WHERE id = ? AND (kind IS NULL OR kind != 'deleted')",
            (agent_id,),
        ).fetchone()
        if row is None:
            raise ValidationError("Agent not found.", code="agent_not_found")
        connection.execute("DELETE FROM agent_credentials WHERE agent_id = ?", (agent_id,))
        connection.execute(
            """
            UPDATE agents
            SET enabled = 0,
                configured = 0,
                execution_enabled = 0,
                health_status = 'deleted',
                kind = 'deleted',
                updated_at = ?
            WHERE id = ?
            """,
            (now, agent_id),
        )
    return {"id": agent_id, "deleted": True}


def get_enabled_agents_by_ids(agent_ids: list[str]) -> list[dict[str, object]]:
    return [agent for agent in get_agents_by_ids(agent_ids) if agent["enabled"]]


def get_agents_by_ids(agent_ids: list[str]) -> list[dict[str, object]]:
    if not agent_ids:
        return []
    placeholders = ",".join("?" for _ in agent_ids)
    with connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM agents WHERE id IN ({placeholders})",
            agent_ids,
        ).fetchall()

    by_id = {row["id"]: enrich_agent_runtime(_agent_from_row(row)) for row in rows}
    return [by_id[agent_id] for agent_id in agent_ids if agent_id in by_id]


def get_agent_profiles_by_ids(agent_ids: list[str]) -> list[dict[str, object]]:
    if not agent_ids:
        return []
    placeholders = ",".join("?" for _ in agent_ids)
    with connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM agents WHERE id IN ({placeholders})",
            agent_ids,
        ).fetchall()
    by_id = {row["id"]: _agent_from_row(row) for row in rows}
    return [by_id[agent_id] for agent_id in agent_ids if agent_id in by_id]


def _agent_from_row(row: Row) -> dict[str, object]:
    provider = row["provider"]
    if row["id"] == "agent-demo-model":
        provider = get_settings().model_agent_provider
    return {
        "id": row["id"],
        "name": row["name"],
        "provider": provider,
        "avatar": row["avatar"],
        "avatar_url": _row_value(row, "avatar_url"),
        "initials": row["initials"],
        "capability_tags": json.loads(row["capability_tags_json"]),
        "adapter_kind": _row_value(row, "adapter_kind"),
        "system_prompt": _row_value(row, "system_prompt"),
        "model": _row_value(row, "model"),
        "api_base": _row_value(row, "api_base"),
        "credential_source": _row_value(row, "credential_source"),
        "executable_path": _row_value(row, "executable_path"),
        "kind": _row_value(row, "kind") or "profile",
        "allowed_tools": json.loads(str(_row_value(row, "allowed_tools_json") or "[]")),
        "enabled": bool(row["enabled"]),
        "execution_enabled": bool(row["execution_enabled"]),
        "configured": bool(row["configured"]),
        "health_status": row["health_status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.", code="agent_profile_invalid")
    return value.strip()


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string.", code="agent_profile_invalid")
    stripped = value.strip()
    return stripped or None


def _optional_secret(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.", code="agent_profile_invalid")
    return value.strip()


def _string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list.", code="agent_profile_invalid")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(f"{field} must contain non-empty strings.", code="agent_profile_invalid")
        result.append(item.strip())
    return result


def _provider_from_body(raw: dict[str, object]) -> str:
    direct = _optional_string(raw.get("provider"), "provider")
    if direct:
        return _resolve_default_provider(direct)
    model = raw.get("model")
    if isinstance(model, dict):
        provider = _optional_string(model.get("provider"), "model.provider")
        if provider:
            return _resolve_default_provider(provider)
    return "custom_openai"


def _resolve_default_provider(provider: str) -> str:
    if provider == "default":
        return get_settings().model_agent_provider or "custom_openai"
    return provider.strip().lower()


def _adapter_kind_from_body(raw: dict[str, object], provider: str) -> str:
    direct = _optional_string(raw.get("adapter_kind"), "adapter_kind")
    if direct:
        return direct
    if provider == "opencode":
        return "opencode_http"
    if provider == "codex":
        return "codex_cli"
    if provider == "anthropic":
        return "claude_code_cli"
    return "custom_openai"


def _kind_from_body(raw: dict[str, object], provider: str, adapter_kind: str) -> str:
    explicit = _optional_string(raw.get("kind"), "kind") or _optional_string(raw.get("agent_type"), "agent_type")
    if explicit in {"custom", "custom_cloud", "cloud"}:
        return "custom"
    if explicit in {"local", "local_cli", "builtin_local"}:
        return "local"
    if adapter_kind in {"codex_cli", "claude_code_cli", "opencode_http"} or provider in {"codex", "anthropic", "opencode"}:
        return "local"
    return "custom"


def _model_from_body(raw: dict[str, object]) -> str | None:
    value = raw.get("model")
    if isinstance(value, str):
        clean = value.strip()
        return None if clean == "default" or not clean else clean
    if isinstance(value, dict):
        model = value.get("model")
        if isinstance(model, str):
            clean = model.strip()
            return None if clean == "default" or not clean else clean
    return None


def _connection_test_required(raw: dict[str, object]) -> bool:
    return raw.get("connection_test_required") is True or raw.get("test_connection") is True


def _connection_test(
    *,
    agent_id: str,
    provider: str,
    adapter_kind: str,
    api_base: str | None,
    model: str | None,
    api_key: str | None,
    executable_path: str | None,
) -> AdapterHealth:
    if adapter_kind == "custom_openai":
        if not api_base or not model or not api_key:
            raise ValidationError(
                "Custom Agent requires base_url, model, and key before it can be saved.",
                code="provider_not_configured",
            )
        health = CustomOpenAIAdapter(
            config=ProviderConfig(
                provider=provider,
                adapter_kind="custom_openai",
                backend_type="model_agent_backend",
                api_base=api_base,
                model=model,
                credential_source=None,
                executable_path=None,
                timeout_seconds=10,
                max_output_tokens=8,
                temperature=0.0,
                workspace_mode="readonly_chat",
                allowed_tools=[],
                health_check_strategy="direct_probe",
            ),
            target_agent_id=agent_id,
            api_key_override=api_key,
        ).health()
        if health.configured:
            return health
        raise ValidationError(
            health.message or "Custom Agent connection test failed.",
            code=health.error_code or "connection_test_failed",
        )

    if adapter_kind in {"codex_cli", "claude_code_cli"}:
        if not executable_path:
            raise ValidationError(
                "Local Agent requires a local executable path before it can be saved.",
                code="adapter_executable_not_found",
            )
        status = enrich_agent_runtime(
            {
                "id": agent_id,
                "provider": provider,
                "adapter_kind": adapter_kind,
                "executable_path": executable_path,
                "execution_enabled": True,
                "configured": True,
                "health_status": "configured",
                "enabled": True,
            }
        )
        if status.get("configured") is True and status.get("execution_enabled") is True:
            from services.api.app.agents.adapter_health import adapter_health

            return adapter_health(
                provider=provider,
                adapter_kind=adapter_kind,
                configured=True,
                status="ready",
                error_code=None,
                recovery_hint=None,
                capabilities=["direct_response"],
                message=str(status.get("runtime_message") or "Local Agent preflight succeeded."),
            )
        raise ValidationError(
            str(status.get("runtime_message") or "Local Agent preflight failed."),
            code=str(status.get("error_code") or "local_agent_preflight_failed"),
        )

    raise ValidationError(
        "This Agent type does not have an executable adapter yet.",
        code="unsupported_provider",
    )


def _credential_source_for_agent(agent_id: str) -> str:
    return f"credential_ref:agent:{agent_id}:api_key"


def _store_agent_secret(connection, *, agent_id: str, secret_name: str, secret_value: str, now: str) -> None:
    connection.execute(
        """
        INSERT INTO agent_credentials (agent_id, secret_name, secret_value, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(agent_id, secret_name) DO UPDATE SET
            secret_value = excluded.secret_value,
            updated_at = excluded.updated_at
        """,
        (agent_id, secret_name, secret_value, now, now),
    )


def _existing_api_key(agent_id: str) -> str | None:
    current = _get_agent_profile_row(agent_id)
    try:
        return credential_value_from_environment(provider_config_from_agent(current))
    except ValidationError:
        return None


def _get_agent_profile_row(agent_id: str) -> dict[str, object]:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM agents WHERE id = ? AND (kind IS NULL OR kind != 'deleted')",
            (agent_id,),
        ).fetchone()
    if row is None:
        raise ValidationError("Agent not found.", code="agent_not_found")
    return _agent_from_row(row)


def _initials(name: str) -> str:
    letters = [part[0] for part in name.split() if part]
    return ("".join(letters) or name[:2]).upper()[:3]


def _row_value(row: Row, key: str) -> object | None:
    return row[key] if key in row.keys() else None
