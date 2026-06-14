from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.api.app.shared.errors import ValidationError
from services.api.app.shared.settings import get_settings


BACKEND_TYPES = {"model_agent_backend", "coding_agent_backend", "tool_integration"}
ADAPTER_KINDS = {"custom_openai", "codex_cli", "claude_code_cli", "opencode_http", "disabled"}
WORKSPACE_MODES = {"none", "read_only", "readonly_chat", "workspace_write"}
HEALTH_CHECK_STRATEGIES = {"direct_probe", "metadata_probe", "none"}

_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_CREDENTIAL_REF_RE = re.compile(r"^credential_ref:[A-Za-z0-9_.:/-]+$")
CUSTOM_OPENAI_PROVIDER_KEYS = (
    "qwen_turbo",
    "volc_deepseek_flash",
    "volc_deepseek_pro",
    "deepseek_official",
)

_PROVIDER_DEFAULTS: dict[str, dict[str, object]] = {
    "custom_openai": {
        "adapter_kind": "custom_openai",
        "credential_env": ["AGENTHUB_CUSTOM_OPENAI_API_KEY", "CUSTOM_OPENAI_API_KEY"],
        "credential_source": "AGENTHUB_CUSTOM_OPENAI_API_KEY",
    },
    "openai": {
        "adapter_kind": "custom_openai",
        "api_base_env": ["AGENTHUB_OPENAI_API_BASE", "OPENAI_API_BASE", "OPENAI_BASE_URL"],
        "model_env": ["AGENTHUB_OPENAI_MODEL", "OPENAI_MODEL"],
        "credential_source": "OPENAI_API_KEY",
    },
    "deepseek": {
        "adapter_kind": "custom_openai",
        "api_base_env": [
            "AGENTHUB_PROVIDER_DEEPSEEK_API_BASE",
            "AGENTHUB_DEEPSEEK_API_BASE",
            "DEEPSEEK_API_BASE",
            "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        ],
        "model_env": [
            "AGENTHUB_PROVIDER_DEEPSEEK_MODEL",
            "AGENTHUB_DEEPSEEK_MODEL",
            "DEEPSEEK_MODEL",
            "AGENTHUB_CUSTOM_OPENAI_MODEL",
        ],
        "credential_env": [
            "AGENTHUB_PROVIDER_DEEPSEEK_API_KEY",
            "AGENTHUB_DEEPSEEK_API_KEY",
            "DEEPSEEK_API_KEY",
            "AGENTHUB_CUSTOM_OPENAI_API_KEY",
        ],
        "credential_source": "DEEPSEEK_API_KEY",
    },
    "zhipu": {
        "adapter_kind": "custom_openai",
        "api_base_env": ["AGENTHUB_ZHIPU_API_BASE", "ZHIPU_API_BASE"],
        "model_env": ["AGENTHUB_ZHIPU_MODEL", "ZHIPU_MODEL"],
        "credential_source": "ZHIPU_API_KEY",
    },
    "doubao": {
        "adapter_kind": "custom_openai",
        "api_base_env": ["AGENTHUB_DOUBAO_API_BASE", "DOUBAO_API_BASE"],
        "model_env": ["AGENTHUB_DOUBAO_MODEL", "DOUBAO_MODEL"],
        "credential_source": "DOUBAO_API_KEY",
    },
    "qwen": {
        "adapter_kind": "custom_openai",
        "api_base_env": [
            "AGENTHUB_PROVIDER_QWEN_API_BASE",
            "AGENTHUB_QWEN_TURBO_API_BASE",
            "AGENTHUB_QWEN_API_BASE",
            "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        ],
        "model_env": [
            "AGENTHUB_PROVIDER_QWEN_MODEL",
            "AGENTHUB_QWEN_TURBO_MODEL",
            "AGENTHUB_QWEN_MODEL",
            "AGENTHUB_CUSTOM_OPENAI_MODEL",
        ],
        "credential_env": [
            "AGENTHUB_PROVIDER_QWEN_API_KEY",
            "AGENTHUB_QWEN_TURBO_API_KEY",
            "AGENTHUB_QWEN_API_KEY",
            "AGENTHUB_CUSTOM_OPENAI_API_KEY",
        ],
        "credential_source": "QWEN_API_KEY",
    },
    "qwen_turbo": {
        "adapter_kind": "custom_openai",
        "api_base_env": [
            "AGENTHUB_PROVIDER_QWEN_API_BASE",
            "AGENTHUB_QWEN_TURBO_API_BASE",
            "AGENTHUB_QWEN_API_BASE",
            "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        ],
        "model_env": [
            "AGENTHUB_PROVIDER_QWEN_MODEL",
            "AGENTHUB_QWEN_TURBO_MODEL",
            "AGENTHUB_QWEN_MODEL",
            "AGENTHUB_CUSTOM_OPENAI_MODEL",
        ],
        "credential_env": [
            "AGENTHUB_PROVIDER_QWEN_API_KEY",
            "AGENTHUB_QWEN_TURBO_API_KEY",
            "AGENTHUB_QWEN_API_KEY",
            "AGENTHUB_CUSTOM_OPENAI_API_KEY",
        ],
        "credential_source": "AGENTHUB_PROVIDER_QWEN_API_KEY",
        "strict_env": True,
    },
    "volc_deepseek_flash": {
        "adapter_kind": "custom_openai",
        "api_base_env": ["AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_BASE"],
        "model_env": ["AGENTHUB_PROVIDER_VOLC_DEEPSEEK_FLASH_MODEL"],
        "credential_source": "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_KEY",
        "strict_env": True,
    },
    "volc_deepseek_pro": {
        "adapter_kind": "custom_openai",
        "api_base_env": ["AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_BASE"],
        "model_env": ["AGENTHUB_PROVIDER_VOLC_DEEPSEEK_PRO_MODEL"],
        "credential_source": "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_KEY",
        "strict_env": True,
    },
    "deepseek_official": {
        "adapter_kind": "custom_openai",
        "api_base_env": [
            "AGENTHUB_PROVIDER_DEEPSEEK_API_BASE",
            "AGENTHUB_DEEPSEEK_API_BASE",
            "DEEPSEEK_API_BASE",
            "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        ],
        "model_env": [
            "AGENTHUB_PROVIDER_DEEPSEEK_MODEL",
            "AGENTHUB_DEEPSEEK_MODEL",
            "DEEPSEEK_MODEL",
            "AGENTHUB_CUSTOM_OPENAI_MODEL",
        ],
        "credential_env": [
            "AGENTHUB_PROVIDER_DEEPSEEK_API_KEY",
            "AGENTHUB_DEEPSEEK_API_KEY",
            "DEEPSEEK_API_KEY",
            "AGENTHUB_CUSTOM_OPENAI_API_KEY",
        ],
        "credential_source": "AGENTHUB_PROVIDER_DEEPSEEK_API_KEY",
        "strict_env": True,
    },
    "openrouter": {
        "adapter_kind": "custom_openai",
        "api_base_env": ["AGENTHUB_OPENROUTER_API_BASE", "OPENROUTER_API_BASE"],
        "model_env": ["AGENTHUB_OPENROUTER_MODEL", "OPENROUTER_MODEL"],
        "credential_source": "OPENROUTER_API_KEY",
    },
    "ollama": {
        "adapter_kind": "custom_openai",
        "api_base_env": ["AGENTHUB_OLLAMA_API_BASE", "OLLAMA_API_BASE"],
        "model_env": ["AGENTHUB_OLLAMA_MODEL", "OLLAMA_MODEL"],
        "credential_source": "OLLAMA_API_KEY",
    },
    "codex": {
        "adapter_kind": "codex_cli",
        "executable_env": ["AGENTHUB_CODEX_EXECUTABLE", "CODEX_EXECUTABLE", "AGENTHUB_CODEX_CLI_EXECUTABLE"],
        "executable_path": "codex",
    },
    "anthropic": {
        "adapter_kind": "claude_code_cli",
        "executable_env": ["AGENTHUB_CLAUDE_CODE_EXECUTABLE", "AGENTHUB_CLAUDE_EXECUTABLE", "CLAUDE_CODE_EXECUTABLE"],
        "executable_path": "claude",
    },
    "opencode": {
        "adapter_kind": "opencode_http",
        "api_base_env": ["OPENCODE_API_BASE", "AGENTHUB_OPENCODE_API_BASE"],
    },
    # Chinese provider name aliases – map to the same env-variable chains as
    # their English counterparts so that runtime resolution works regardless of
    # which name the agent profile stores.
    "深度求索": {
        "adapter_kind": "custom_openai",
        "api_base_env": [
            "AGENTHUB_PROVIDER_DEEPSEEK_API_BASE",
            "AGENTHUB_DEEPSEEK_API_BASE",
            "DEEPSEEK_API_BASE",
            "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        ],
        "model_env": [
            "AGENTHUB_PROVIDER_DEEPSEEK_MODEL",
            "AGENTHUB_DEEPSEEK_MODEL",
            "DEEPSEEK_MODEL",
            "AGENTHUB_CUSTOM_OPENAI_MODEL",
        ],
        "credential_env": [
            "AGENTHUB_PROVIDER_DEEPSEEK_API_KEY",
            "AGENTHUB_DEEPSEEK_API_KEY",
            "DEEPSEEK_API_KEY",
            "AGENTHUB_CUSTOM_OPENAI_API_KEY",
        ],
        "credential_source": "DEEPSEEK_API_KEY",
    },
    "阿里千问": {
        "adapter_kind": "custom_openai",
        "api_base_env": [
            "AGENTHUB_PROVIDER_QWEN_API_BASE",
            "AGENTHUB_QWEN_TURBO_API_BASE",
            "AGENTHUB_QWEN_API_BASE",
            "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        ],
        "model_env": [
            "AGENTHUB_PROVIDER_QWEN_MODEL",
            "AGENTHUB_QWEN_TURBO_MODEL",
            "AGENTHUB_QWEN_MODEL",
            "AGENTHUB_CUSTOM_OPENAI_MODEL",
        ],
        "credential_env": [
            "AGENTHUB_PROVIDER_QWEN_API_KEY",
            "AGENTHUB_QWEN_TURBO_API_KEY",
            "AGENTHUB_QWEN_API_KEY",
            "AGENTHUB_CUSTOM_OPENAI_API_KEY",
        ],
        "credential_source": "QWEN_API_KEY",
    },
    "千问": {
        "adapter_kind": "custom_openai",
        "api_base_env": [
            "AGENTHUB_PROVIDER_QWEN_API_BASE",
            "AGENTHUB_QWEN_TURBO_API_BASE",
            "AGENTHUB_QWEN_API_BASE",
            "AGENTHUB_CUSTOM_OPENAI_API_BASE",
        ],
        "model_env": [
            "AGENTHUB_PROVIDER_QWEN_MODEL",
            "AGENTHUB_QWEN_TURBO_MODEL",
            "AGENTHUB_QWEN_MODEL",
            "AGENTHUB_CUSTOM_OPENAI_MODEL",
        ],
        "credential_env": [
            "AGENTHUB_PROVIDER_QWEN_API_KEY",
            "AGENTHUB_QWEN_TURBO_API_KEY",
            "AGENTHUB_QWEN_API_KEY",
            "AGENTHUB_CUSTOM_OPENAI_API_KEY",
        ],
        "credential_source": "QWEN_API_KEY",
    },
    "智谱": {
        "adapter_kind": "custom_openai",
        "api_base_env": ["AGENTHUB_ZHIPU_API_BASE", "ZHIPU_API_BASE"],
        "model_env": ["AGENTHUB_ZHIPU_MODEL", "ZHIPU_MODEL"],
        "credential_source": "ZHIPU_API_KEY",
    },
    "豆包": {
        "adapter_kind": "custom_openai",
        "api_base_env": ["AGENTHUB_DOUBAO_API_BASE", "DOUBAO_API_BASE"],
        "model_env": ["AGENTHUB_DOUBAO_MODEL", "DOUBAO_MODEL"],
        "credential_source": "DOUBAO_API_KEY",
    },
}


@dataclass(frozen=True)
class ProviderConfig:
    provider: str | None
    adapter_kind: str
    backend_type: str
    api_base: str | None
    model: str | None
    credential_source: str | dict[str, str] | None
    executable_path: str | None
    timeout_seconds: int
    max_output_tokens: int
    temperature: float
    workspace_mode: str
    allowed_tools: list[str]
    health_check_strategy: str


def validate_provider_config(raw: dict[str, Any]) -> ProviderConfig:
    if not isinstance(raw, dict):
        raise ValidationError("ProviderConfig must be an object.", code="provider_config_invalid")

    provider = _optional_clean_string(raw.get("provider"), "provider")
    adapter_kind = _enum(raw, "adapter_kind", ADAPTER_KINDS)
    backend_type = _enum(raw, "backend_type", BACKEND_TYPES)
    _validate_adapter_backend_pair(adapter_kind, backend_type)

    config = ProviderConfig(
        provider=provider,
        adapter_kind=adapter_kind,
        backend_type=backend_type,
        api_base=_optional_clean_string(raw.get("api_base"), "api_base"),
        model=_optional_clean_string(raw.get("model"), "model"),
        credential_source=_credential_source(raw.get("credential_source")),
        executable_path=_optional_clean_string(raw.get("executable_path"), "executable_path"),
        timeout_seconds=_positive_int(raw.get("timeout_seconds"), "timeout_seconds", default=30),
        max_output_tokens=_positive_int(raw.get("max_output_tokens"), "max_output_tokens", default=4096),
        temperature=_temperature(raw.get("temperature")),
        workspace_mode=_enum(raw, "workspace_mode", WORKSPACE_MODES),
        allowed_tools=_string_list(raw.get("allowed_tools"), "allowed_tools"),
        health_check_strategy=_enum(raw, "health_check_strategy", HEALTH_CHECK_STRATEGIES),
    )
    _reject_secret_like_config(config)
    return config


def provider_config_from_agent(agent_profile: dict[str, object]) -> ProviderConfig:
    provider = _provider(agent_profile)
    defaults = _PROVIDER_DEFAULTS.get(provider or "", {})
    adapter_kind = _profile_string(agent_profile, "adapter_kind") or str(defaults.get("adapter_kind") or "disabled")
    allow_generic_env = defaults.get("strict_env") is not True

    raw = {
        "provider": provider,
        "adapter_kind": adapter_kind,
        "backend_type": _backend_type_for_adapter(adapter_kind),
        "api_base": _profile_string(agent_profile, "api_base")
        or _first_env(defaults.get("api_base_env"))
        or _first_env([f"AGENTHUB_{_env_key(provider)}_API_BASE"] if provider and allow_generic_env else None),
        "model": _profile_string(agent_profile, "model")
        or _first_env(defaults.get("model_env"))
        or _first_env([f"AGENTHUB_{_env_key(provider)}_MODEL"] if provider and allow_generic_env else None),
        "credential_source": _profile_credential_source(agent_profile)
        or _first_env([f"AGENTHUB_{_env_key(provider)}_CREDENTIAL_SOURCE"] if provider and allow_generic_env else None)
        or _first_env_name(defaults.get("credential_env"))
        or defaults.get("credential_source"),
        "executable_path": _profile_string(agent_profile, "executable_path")
        or _first_executable_env(defaults.get("executable_env"))
        or defaults.get("executable_path"),
        "timeout_seconds": _profile_int(agent_profile, "timeout_seconds")
        or _first_env_int([f"AGENTHUB_{_env_key(provider)}_TIMEOUT_SECONDS"] if provider else None)
        or 30,
        "max_output_tokens": _profile_int(agent_profile, "max_output_tokens")
        or _first_env_int([f"AGENTHUB_{_env_key(provider)}_MAX_OUTPUT_TOKENS"] if provider else None)
        or 4096,
        "temperature": _profile_float(agent_profile, "temperature")
        or _first_env_float([f"AGENTHUB_{_env_key(provider)}_TEMPERATURE"] if provider else None)
        or 0.2,
        "workspace_mode": _profile_string(agent_profile, "workspace_mode")
        or (
            "read_only"
            if adapter_kind in {"codex_cli", "claude_code_cli"}
            else "readonly_chat"
            if adapter_kind == "custom_openai"
            else "none"
        ),
        "allowed_tools": _profile_string_list(agent_profile, "allowed_tools"),
        "health_check_strategy": _profile_string(agent_profile, "health_check_strategy") or "direct_probe",
    }
    return validate_provider_config(raw)


def custom_openai_provider_config(provider_key: str) -> ProviderConfig:
    clean = provider_key.strip().lower() if isinstance(provider_key, str) else ""
    if clean not in CUSTOM_OPENAI_PROVIDER_KEYS:
        raise ValidationError(
            f"Unsupported A7-3.1 custom_openai provider: {provider_key}",
            code="provider_config_invalid_provider",
        )
    return provider_config_from_agent(
        {
            "provider": clean,
            "adapter_kind": "custom_openai",
            "execution_enabled": True,
            "configured": True,
            "health_status": "configured",
        }
    )


def custom_openai_provider_configs_from_environment() -> dict[str, ProviderConfig]:
    return {provider_key: custom_openai_provider_config(provider_key) for provider_key in CUSTOM_OPENAI_PROVIDER_KEYS}


def credential_env_name(config: ProviderConfig) -> str | None:
    if isinstance(config.credential_source, str) and _ENV_NAME_RE.match(config.credential_source):
        return config.credential_source
    return None


def credential_value_from_environment(config: ProviderConfig) -> str | None:
    if isinstance(config.credential_source, str) and config.credential_source.startswith("credential_ref:agent:"):
        return _credential_value_from_agent_ref(config.credential_source)
    env_name = credential_env_name(config)
    if env_name is None:
        return None
    value = _env_value(env_name)
    return value if isinstance(value, str) and value.strip() else None


def _credential_value_from_agent_ref(source: str) -> str | None:
    parts = source.split(":")
    if len(parts) < 4 or parts[0] != "credential_ref" or parts[1] != "agent":
        return None
    agent_id = parts[2].strip()
    secret_name = parts[3].strip() or "api_key"
    if not agent_id:
        return None
    from services.api.app.shared.database import connect

    with connect() as connection:
        row = connection.execute(
            """
            SELECT secret_value
            FROM agent_credentials
            WHERE agent_id = ? AND secret_name = ?
            """,
            (agent_id, secret_name),
        ).fetchone()
    if row is None:
        return None
    value = row["secret_value"]
    return value if isinstance(value, str) and value.strip() else None


def _validate_adapter_backend_pair(adapter_kind: str, backend_type: str) -> None:
    if adapter_kind == "custom_openai" and backend_type != "model_agent_backend":
        raise ValidationError(
            "custom_openai requires backend_type=model_agent_backend.",
            code="provider_config_adapter_backend_mismatch",
        )
    if adapter_kind in {"codex_cli", "claude_code_cli", "opencode_http"} and backend_type != "coding_agent_backend":
        raise ValidationError(
            f"{adapter_kind} requires backend_type=coding_agent_backend.",
            code="provider_config_adapter_backend_mismatch",
        )
    if adapter_kind == "disabled" and backend_type == "tool_integration":
        raise ValidationError(
            "disabled Agent Adapters cannot use backend_type=tool_integration.",
            code="provider_config_adapter_backend_mismatch",
        )


def _backend_type_for_adapter(adapter_kind: str) -> str:
    if adapter_kind == "custom_openai":
        return "model_agent_backend"
    if adapter_kind in {"codex_cli", "claude_code_cli", "opencode_http"}:
        return "coding_agent_backend"
    return "model_agent_backend"


def _credential_source(value: object) -> str | dict[str, str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        clean = value.strip()
        if _ENV_NAME_RE.match(clean) or _CREDENTIAL_REF_RE.match(clean):
            return clean
        raise ValidationError(
            "credential_source must be an environment variable name or CredentialRef.",
            code="provider_config_invalid_credential_source",
        )
    if isinstance(value, dict):
        forbidden = {"value", "secret", "api_key", "token", "password"}
        if any(key in value for key in forbidden):
            raise ValidationError(
                "credential_source must not contain raw secret values.",
                code="provider_config_secret_value_forbidden",
            )
        if value.get("type") != "credential_ref" or not isinstance(value.get("ref"), str) or not value["ref"].strip():
            raise ValidationError(
                "CredentialRef must have type=credential_ref and a non-empty ref.",
                code="provider_config_invalid_credential_source",
            )
        return {"type": "credential_ref", "ref": value["ref"].strip()}
    raise ValidationError(
        "credential_source must be an environment variable name or CredentialRef.",
        code="provider_config_invalid_credential_source",
    )


def _reject_secret_like_config(config: ProviderConfig) -> None:
    for field in ("api_base", "model", "executable_path"):
        value = getattr(config, field)
        if isinstance(value, str) and _looks_like_secret(value):
            raise ValidationError(
                f"{field} must not contain raw secret values.",
                code="provider_config_secret_value_forbidden",
            )


def _looks_like_secret(value: str) -> bool:
    clean = value.strip()
    secret_prefixes = ("sk-", "sk_", "sk-proj-", "ghp_", "xoxb-", "ya29.", "Bearer ")
    return clean.startswith(secret_prefixes)


def _enum(raw: dict[str, Any], field: str, allowed: set[str]) -> str:
    value = _required_clean_string(raw.get(field), field)
    if value not in allowed:
        raise ValidationError(f"Unsupported {field}: {value}", code=f"provider_config_invalid_{field}")
    return value


def _required_clean_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.", code="provider_config_invalid")
    return value.strip()


def _optional_clean_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_clean_string(value, field)


def _positive_int(value: object, field: str, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValidationError(f"{field} must be a positive integer.", code="provider_config_invalid")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a positive integer.", code="provider_config_invalid") from exc
    if parsed <= 0:
        raise ValidationError(f"{field} must be a positive integer.", code="provider_config_invalid")
    return parsed


def _temperature(value: object) -> float:
    if value is None:
        return 0.2
    if isinstance(value, bool):
        raise ValidationError("temperature must be a number.", code="provider_config_invalid")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("temperature must be a number.", code="provider_config_invalid") from exc
    if parsed < 0:
        raise ValidationError("temperature must be non-negative.", code="provider_config_invalid")
    return parsed


def _string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list.", code="provider_config_invalid")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(f"{field} must contain non-empty strings.", code="provider_config_invalid")
        result.append(item.strip())
    return result


def _provider(agent_profile: dict[str, object]) -> str | None:
    value = agent_profile.get("provider")
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def _profile_string(agent_profile: dict[str, object], field: str) -> str | None:
    value = agent_profile.get(field)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _profile_int(agent_profile: dict[str, object], field: str) -> int | None:
    value = agent_profile.get(field)
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _profile_float(agent_profile: dict[str, object], field: str) -> float | None:
    value = agent_profile.get(field)
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _profile_string_list(agent_profile: dict[str, object], field: str) -> list[str]:
    value = agent_profile.get(field)
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _profile_credential_source(agent_profile: dict[str, object]) -> object | None:
    value = agent_profile.get("credential_source")
    if isinstance(value, (str, dict)):
        return value
    return None


def _first_env(names: object) -> str | None:
    if not isinstance(names, list):
        return None
    for name in names:
        if not isinstance(name, str):
            continue
        value = _env_value(name)
        if value:
            return value
    return None


def _first_env_name(names: object) -> str | None:
    if not isinstance(names, list):
        return None
    for name in names:
        if not isinstance(name, str):
            continue
        if _env_value(name):
            return name
    return None


def _first_executable_env(names: object) -> str | None:
    if not isinstance(names, list):
        return None
    first_configured: str | None = None
    for name in names:
        if not isinstance(name, str):
            continue
        value = _env_value(name)
        if not value:
            continue
        if first_configured is None:
            first_configured = value
        if _executable_candidate_exists(value):
            return value
    return first_configured


def _first_env_int(names: object) -> int | None:
    value = _first_env(names)
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _first_env_float(names: object) -> float | None:
    value = _first_env(names)
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _env_key(provider: str | None) -> str:
    if not provider:
        return "UNKNOWN"
    return re.sub(r"[^A-Z0-9]+", "_", provider.upper()).strip("_") or "UNKNOWN"


def _env_value(name: str) -> str | None:
    value = get_settings().env_value(name)
    if value is not None:
        return value
    return os.getenv(name)


def _executable_candidate_exists(value: str) -> bool:
    clean = value.strip().strip('"').strip("'")
    if any(separator in clean for separator in ("/", "\\")):
        return Path(clean).expanduser().exists()
    return shutil.which(clean) is not None
