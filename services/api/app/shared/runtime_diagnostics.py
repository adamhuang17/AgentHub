from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.api.app.agents.repository import list_agents
from services.api.app.shared.settings import Settings, get_settings


def runtime_diagnostics(
    *,
    profile: str | None = None,
    env_file: str | None = None,
    check_writable: bool = False,
) -> dict[str, object]:
    settings = get_settings(profile=profile, env_file=env_file)
    loaded_env = settings.loaded_environment
    warnings: list[str] = []
    agents = _safe_agents(warnings)
    codex_status = _agent_status(agents, "codex")
    claude_status = _agent_status(agents, "anthropic")
    custom_openai_status = _custom_openai_status(agents, settings.model_agent_provider)
    payload: dict[str, object] = {
        "api_status": "ok",
        "env_profile": settings.env_profile,
        "agenthub_env": settings.agenthub_env,
        "loaded_env_files": loaded_env.files_loaded,
        "explicit_env_file_configured": loaded_env.explicit_env_file_configured,
        "explicit_env_file_used": loaded_env.explicit_env_file_used,
        "db_configured": bool(settings.db_path),
        "artifact_store_configured": bool(settings.artifact_store_dir),
        "turn_router_backend": settings.turn_router_backend,
        "turn_router_configured": settings.turn_router_configured(),
        "agents_enabled_count": sum(1 for agent in agents if agent.get("enabled") is True),
        "agents_configured_count": sum(1 for agent in agents if agent.get("configured") is True),
        "codex_cli_configured": bool(codex_status and codex_status.get("configured") is True),
        "codex_cli_runtime_status": codex_status.get("runtime_status") if codex_status else "not_configured",
        "codex_cli_error_code": codex_status.get("error_code") if codex_status else "codex_executable_missing",
        "codex_executable_detected_path": (
            codex_status.get("executable_detected_path") if codex_status else None
        ),
        "codex_preflight_command": codex_status.get("preflight_command") if codex_status else "codex --version",
        "claude_code_cli_configured": bool(claude_status and claude_status.get("configured") is True),
        "claude_code_cli_runtime_status": claude_status.get("runtime_status") if claude_status else "not_configured",
        "claude_code_cli_error_code": claude_status.get("error_code") if claude_status else "claude_executable_missing",
        "custom_openai_configured": bool(custom_openai_status and custom_openai_status.get("configured") is True),
        "custom_openai_runtime_status": (
            custom_openai_status.get("runtime_status") if custom_openai_status else "not_configured"
        ),
        "custom_openai_error_code": (
            custom_openai_status.get("error_code") if custom_openai_status else "provider_not_configured"
        ),
        "provider_alias_used": settings.model_agent_api_base_alias,
        "model_alias_used": settings.model_agent_model_alias,
        "key_alias_used": settings.model_agent_api_key_alias,
        "static_deploy_configured": settings.static_deploy_dir is not None,
        "agents": [_agent_runtime_payload(agent) for agent in agents],
        "warnings": warnings,
    }
    if check_writable:
        payload["db_writable"] = _path_parent_writable(settings.db_path, warnings, "db_path")
        payload["artifact_store_writable"] = _dir_writable(settings.artifact_store_dir, warnings, "artifact_store")
        if settings.static_deploy_dir is not None:
            payload["static_deploy_writable"] = _dir_writable(settings.static_deploy_dir, warnings, "static_deploy")
    _append_warnings(settings, payload, warnings)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Print AgentHub runtime diagnostics without secrets.")
    parser.add_argument("--profile", choices=["demo", "test", "real"], default=None)
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--check-writable", action="store_true")
    args = parser.parse_args()
    print(json.dumps(runtime_diagnostics(profile=args.profile, env_file=args.env_file, check_writable=args.check_writable), indent=2))


def _safe_agents(warnings: list[str]) -> list[dict[str, object]]:
    try:
        return list_agents()
    except Exception as exc:
        warnings.append(f"agents_unavailable:{type(exc).__name__}")
        return []


def _append_warnings(settings: Settings, payload: dict[str, object], warnings: list[str]) -> None:
    loaded_env = settings.loaded_environment
    if not payload["turn_router_configured"]:
        warnings.append("turn_router_not_configured")
    if not payload["codex_cli_configured"]:
        warnings.append(str(payload["codex_cli_error_code"] or "codex_cli_not_configured"))
    if not payload["claude_code_cli_configured"]:
        warnings.append(str(payload["claude_code_cli_error_code"] or "claude_code_cli_not_configured"))
    if not payload["custom_openai_configured"]:
        warnings.append("custom_openai_not_configured")
    if settings.static_deploy_dir is None:
        warnings.append("static_deploy_not_configured")
    # Warn when AGENTHUB_ENV_FILE was set but the file was not found
    if loaded_env.explicit_env_file_configured and not loaded_env.explicit_env_file_used:
        warnings.append("env_file_not_found")


def _agent_status(agents: list[dict[str, object]], provider: str) -> dict[str, object] | None:
    for agent in agents:
        if str(agent.get("provider") or "").strip().lower() == provider:
            return agent
    return None


def _custom_openai_status(agents: list[dict[str, object]], configured_provider: str) -> dict[str, object] | None:
    providers = {
        "custom_openai",
        "openai",
        "deepseek",
        "zhipu",
        "doubao",
        "qwen",
        "qwen_turbo",
        "volc_deepseek_flash",
        "volc_deepseek_pro",
        "deepseek_official",
        "openrouter",
        "ollama",
        configured_provider.strip().lower(),
    }
    for agent in agents:
        if str(agent.get("provider") or "").strip().lower() in providers:
            return agent
    return None


def _agent_runtime_payload(agent: dict[str, object]) -> dict[str, object]:
    keys = [
        "id",
        "name",
        "provider",
        "enabled",
        "configured",
        "execution_enabled",
        "health_status",
        "runtime_status",
        "error_code",
        "executable_path_configured",
        "credentials_configured",
        "runtime_checked_at",
        "runtime_message",
        "recovery_hint",
        "executable_detected_path",
        "preflight_command",
    ]
    return {key: agent.get(key) for key in keys if key in agent}


def _path_parent_writable(path: Path, warnings: list[str], label: str) -> bool:
    return _dir_writable(path.expanduser().parent, warnings, label)


def _dir_writable(path: Path, warnings: list[str], label: str) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".agenthub_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        warnings.append(f"{label}_not_writable")
        return False


if __name__ == "__main__":
    main()
