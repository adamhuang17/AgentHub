from __future__ import annotations

import os
import socket
from dataclasses import dataclass, replace
from pathlib import Path
from urllib import error, request

from services.api.app.agents.adapters.cli_process import CliProcessResult, run_cli_process
from services.api.app.agents.adapters.codex_cli import resolve_executable
from services.api.app.agents.adapters.parsers.codex_jsonl import codex_text_has_auth_failure
from services.api.app.agents.provider_config import (
    ProviderConfig,
    credential_value_from_environment,
    provider_config_from_agent,
)
from services.api.app.shared.settings import get_settings
from services.api.app.shared.time import utc_now


@dataclass(frozen=True)
class AgentRuntimeStatus:
    configured: bool
    execution_enabled: bool
    health_status: str
    runtime_status: str
    error_code: str | None
    executable_path_configured: bool
    credentials_configured: bool
    checked_at: str
    message: str | None = None
    recovery_hint: str | None = None
    executable_detected_path: str | None = None
    preflight_command: str | None = None


def enrich_agent_runtime(agent: dict[str, object]) -> dict[str, object]:
    status = runtime_status_for_agent(agent)
    enriched = dict(agent)
    enriched.update(
        {
            "configured": status.configured,
            "execution_enabled": status.execution_enabled,
            "health_status": status.health_status,
            "runtime_status": status.runtime_status,
            "error_code": status.error_code,
            "executable_path_configured": status.executable_path_configured,
            "credentials_configured": status.credentials_configured,
            "runtime_checked_at": status.checked_at,
        }
    )
    if status.message is not None:
        enriched["runtime_message"] = status.message
    if status.recovery_hint is not None:
        enriched["recovery_hint"] = status.recovery_hint
    if status.executable_detected_path is not None:
        enriched["executable_detected_path"] = status.executable_detected_path
    if status.preflight_command is not None:
        enriched["preflight_command"] = status.preflight_command
    return enriched


def runtime_status_for_agent(agent: dict[str, object]) -> AgentRuntimeStatus:
    provider = _provider(agent)
    if provider == "codex":
        return _cli_status(
            agent,
            executable_label="Codex CLI",
            version_args=["--version"],
            missing_code="codex_executable_missing",
            preflight_failed_code="codex_preflight_failed",
            auth_failed_code="codex_auth_failed",
            recovery_env="AGENTHUB_CODEX_EXECUTABLE",
            auth_detector=codex_text_has_auth_failure,
        )
    if provider == "anthropic":
        return _cli_status(
            agent,
            executable_label="Claude Code CLI",
            version_args=["--version"],
            missing_code="claude_executable_missing",
            preflight_failed_code="claude_preflight_failed",
            auth_failed_code="claude_auth_failed",
            recovery_env="AGENTHUB_CLAUDE_CODE_EXECUTABLE",
            auth_detector=_text_has_auth_failure,
        )
    if provider == "opencode":
        return _opencode_status(agent)
    if _custom_openai_provider(provider):
        return _custom_openai_status(agent)
    return _profile_status(agent)


def _cli_status(
    agent: dict[str, object],
    *,
    executable_label: str,
    version_args: list[str],
    missing_code: str,
    preflight_failed_code: str,
    auth_failed_code: str,
    recovery_env: str,
    auth_detector,
) -> AgentRuntimeStatus:
    config = provider_config_from_agent(agent)
    executable = resolve_executable(config.executable_path)
    preflight_command = _preflight_command(config.executable_path or executable_label, version_args)
    if executable is None:
        return AgentRuntimeStatus(
            configured=False,
            execution_enabled=False,
            health_status="not_configured",
            runtime_status="not_configured",
            error_code=missing_code,
            executable_path_configured=False,
            credentials_configured=False,
            checked_at=utc_now(),
            message=f"{executable_label} executable was not found.",
            recovery_hint=f"Install {executable_label} or set {recovery_env}.",
            preflight_command=preflight_command,
        )

    preflight_command = _preflight_command(executable, version_args)
    result = _run_version_preflight(executable, version_args, config)
    combined_output = "\n".join([*result.stdout_lines, *result.stderr_lines]) if result is not None else ""
    if result is None:
        return AgentRuntimeStatus(
            configured=True,
            execution_enabled=False,
            health_status="unavailable",
            runtime_status="preflight_failed",
            error_code=preflight_failed_code,
            executable_path_configured=True,
            credentials_configured=False,
            checked_at=utc_now(),
            message=f"{executable_label} executable could not be started.",
            recovery_hint=f"Check the configured {recovery_env} path and file permissions.",
            executable_detected_path=executable,
            preflight_command=preflight_command,
        )
    if result.timed_out:
        return AgentRuntimeStatus(
            configured=True,
            execution_enabled=False,
            health_status="unavailable",
            runtime_status="preflight_failed",
            error_code=preflight_failed_code,
            executable_path_configured=True,
            credentials_configured=False,
            checked_at=utc_now(),
            message=f"{executable_label} --version timed out.",
            recovery_hint=f"Run {Path(executable).name} --version locally and fix the CLI before retrying.",
            executable_detected_path=executable,
            preflight_command=preflight_command,
        )
    if auth_detector(combined_output):
        return AgentRuntimeStatus(
            configured=True,
            execution_enabled=False,
            health_status="missing_credentials",
            runtime_status="auth_failed",
            error_code=auth_failed_code,
            executable_path_configured=True,
            credentials_configured=False,
            checked_at=utc_now(),
            message=f"{executable_label} preflight reported an authentication failure.",
            recovery_hint=f"Authenticate {executable_label} for non-interactive use, then retry.",
            executable_detected_path=executable,
            preflight_command=preflight_command,
        )
    if result.exit_code != 0:
        return AgentRuntimeStatus(
            configured=True,
            execution_enabled=False,
            health_status="unavailable",
            runtime_status="preflight_failed",
            error_code=preflight_failed_code,
            executable_path_configured=True,
            credentials_configured=False,
            checked_at=utc_now(),
            message=f"{executable_label} --version exited with code {result.exit_code}.",
            recovery_hint=f"Check the configured {recovery_env} path and CLI installation.",
            executable_detected_path=executable,
            preflight_command=preflight_command,
        )

    return AgentRuntimeStatus(
        configured=True,
        execution_enabled=True,
        health_status="ready",
        runtime_status="ready",
        error_code=None,
        executable_path_configured=True,
        credentials_configured=True,
        checked_at=utc_now(),
        message=f"{executable_label} executable preflight succeeded.",
        recovery_hint=None,
        executable_detected_path=executable,
        preflight_command=preflight_command,
    )


def _run_version_preflight(
    executable: str,
    version_args: list[str],
    config: ProviderConfig,
) -> CliProcessResult | None:
    timeout_seconds = min(max(int(config.timeout_seconds or 1), 1), 5)
    try:
        return run_cli_process(
            [executable, *version_args],
            cwd=os.getcwd(),
            timeout_seconds=timeout_seconds,
        )
    except (OSError, ValueError):
        return None


def _custom_openai_status(agent: dict[str, object]) -> AgentRuntimeStatus:
    config = provider_config_from_agent(agent)
    api_configured = bool(config.api_base and config.model)
    credentials_configured = credential_value_from_environment(config) is not None
    if api_configured and credentials_configured:
        from services.api.app.agents.adapters.custom_openai import CustomOpenAIAdapter

        probe_config = replace(
            config,
            timeout_seconds=min(max(config.timeout_seconds, 1), 5),
            max_output_tokens=min(max(config.max_output_tokens, 1), 8),
            temperature=0.0,
        )
        health = CustomOpenAIAdapter(config=probe_config, target_agent_id=_agent_id(agent)).health()
        if health.configured:
            return AgentRuntimeStatus(
                configured=True,
                execution_enabled=True,
                health_status="ready",
                runtime_status="ready",
                error_code=None,
                executable_path_configured=False,
                credentials_configured=True,
                checked_at=utc_now(),
                message=health.message or "custom_openai direct_response probe succeeded.",
            )
        return AgentRuntimeStatus(
            configured=False,
            execution_enabled=False,
            health_status=health.status,
            runtime_status=health.status,
            error_code=health.error_code or "connection_test_failed",
            executable_path_configured=False,
            credentials_configured=True,
            checked_at=health.checked_at,
            message=health.message or "custom_openai probe failed.",
            recovery_hint=health.recovery_hint,
        )
    if not api_configured:
        return AgentRuntimeStatus(
            configured=False,
            execution_enabled=False,
            health_status="not_configured",
            runtime_status="not_configured",
            error_code="provider_not_configured",
            executable_path_configured=False,
            credentials_configured=credentials_configured,
            checked_at=utc_now(),
            message="custom_openai api_base or model is missing.",
            recovery_hint="Configure provider api_base, model, and API key.",
        )
    return AgentRuntimeStatus(
        configured=False,
        execution_enabled=False,
        health_status="missing_credentials",
        runtime_status="missing_credentials",
        error_code="missing_credentials",
        executable_path_configured=False,
        credentials_configured=False,
        checked_at=utc_now(),
        message="custom_openai API key is missing.",
        recovery_hint="Set the provider API key environment variable.",
    )


def _opencode_status(agent: dict[str, object]) -> AgentRuntimeStatus:
    config = provider_config_from_agent(agent)
    api_base = (config.api_base or get_settings().opencode_api_base or "").rstrip("/")
    if not api_base:
        return AgentRuntimeStatus(
            configured=False,
            execution_enabled=False,
            health_status="not_configured",
            runtime_status="not_configured",
            error_code="provider_not_configured",
            executable_path_configured=False,
            credentials_configured=False,
            checked_at=utc_now(),
            message="AgentHub coding runtime API base is not configured.",
            recovery_hint="Set OPENCODE_API_BASE to the running AgentHub coding runtime.",
        )

    ok, message = _probe_opencode(api_base, timeout_seconds=min(config.timeout_seconds, 5))
    if not ok:
        return AgentRuntimeStatus(
            configured=True,
            execution_enabled=False,
            health_status="unavailable",
            runtime_status="unavailable",
            error_code="opencode_server_unavailable",
            executable_path_configured=False,
            credentials_configured=True,
            checked_at=utc_now(),
            message=message,
            recovery_hint="Start AgentHub coding runtime with `scripts/dev-agent-runtime.ps1` and set OPENCODE_API_BASE.",
        )

    return AgentRuntimeStatus(
        configured=True,
        execution_enabled=True,
        health_status="ready",
        runtime_status="ready",
        error_code=None,
        executable_path_configured=False,
        credentials_configured=True,
        checked_at=utc_now(),
        message="AgentHub coding runtime probe succeeded.",
    )


def _probe_opencode(api_base: str, *, timeout_seconds: int) -> tuple[bool, str]:
    for path in ("/session?limit=1", "/session/status"):
        url = f"{api_base}{path}"
        try:
            req = request.Request(url, method="GET", headers={"Accept": "application/json"})
            with _urlopen_without_proxy(req, timeout_seconds=timeout_seconds) as response:
                if 200 <= int(response.status) < 300:
                    return True, "AgentHub coding runtime is reachable."
        except error.HTTPError as exc:
            if 200 <= exc.code < 300:
                return True, "AgentHub coding runtime is reachable."
            last = f"AgentHub coding runtime probe returned HTTP {exc.code}."
        except (error.URLError, TimeoutError, socket.timeout) as exc:
            last = f"AgentHub coding runtime probe failed: {exc}."
    return False, last if "last" in locals() else "AgentHub coding runtime probe failed."


def _profile_status(agent: dict[str, object]) -> AgentRuntimeStatus:
    configured = agent.get("configured") is True
    execution_enabled = agent.get("execution_enabled") is True
    health_status = str(agent.get("health_status") or ("configured" if configured else "profile_only"))
    return AgentRuntimeStatus(
        configured=configured,
        execution_enabled=execution_enabled,
        health_status=health_status,
        runtime_status=health_status,
        error_code=None if configured else "provider_not_configured",
        executable_path_configured=False,
        credentials_configured=configured,
        checked_at=utc_now(),
    )


def _urlopen_without_proxy(req: request.Request, *, timeout_seconds: int):
    opener = request.build_opener(request.ProxyHandler({}))
    return opener.open(req, timeout=timeout_seconds)


def _custom_openai_provider(provider: str | None) -> bool:
    if provider in {
        "custom_openai",
        "openai",
        "deepseek",
        "深度求索",
        "zhipu",
        "智谱",
        "doubao",
        "豆包",
        "qwen",
        "qwen_turbo",
        "阿里千问",
        "千问",
        "volc_deepseek_flash",
        "volc_deepseek_pro",
        "deepseek_official",
        "openrouter",
        "ollama",
    }:
        return True
    settings = get_settings()
    return bool(provider and provider == settings.model_agent_provider.strip().lower())


def _provider(agent: dict[str, object]) -> str | None:
    value = agent.get("provider")
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def _agent_id(agent: dict[str, object]) -> str | None:
    value = agent.get("id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _text_has_auth_failure(text: str) -> bool:
    clean = text.lower()
    return any(
        marker in clean
        for marker in (
            "auth",
            "unauthorized",
            "permission denied",
            "login required",
            "not logged in",
            "invalid api key",
            "invalid token",
            "401",
            "403",
        )
    )


def _preflight_command(executable: str, args: list[str]) -> str:
    command_name = Path(executable).name or executable
    return " ".join([command_name, *args])
