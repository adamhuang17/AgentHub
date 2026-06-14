from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from services.api.app.agent_runs.schema import AgentRunEventDraft, AgentRunRequest
from services.api.app.agents.adapter_health import AdapterHealth, adapter_health
from services.api.app.agents.adapters.cli_process import CliProcessResult, CliRawLine, run_cli_process
from services.api.app.agents.adapters.parsers.codex_jsonl import (
    codex_event_has_auth_failure,
    codex_text_has_auth_failure,
    parse_codex_jsonl_line,
)
from services.api.app.agents.provider_config import ProviderConfig
from services.api.app.memory.prompt_context import (
    apply_output_format_instruction as _apply_output_format_instruction,
    enrich_cli_prompt as _enrich_prompt_with_context,
)
from services.api.app.shared.settings import get_settings


class CodexCliAdapter:
    adapter_id = "codex_cli"

    def __init__(self, *, config: ProviderConfig, target_agent_id: str | None = None) -> None:
        self.config = config
        self.target_agent_id = target_agent_id

    def health(self) -> AdapterHealth:
        executable = resolve_executable(self.config.executable_path)
        if executable is None:
            return adapter_health(
                provider=self.config.provider,
                adapter_kind=self.adapter_id,
                configured=False,
                status="unavailable",
                error_code="adapter_executable_not_found",
                recovery_hint="Install Codex CLI or set AGENTHUB_CODEX_EXECUTABLE.",
                capabilities=[],
                message="Codex CLI executable was not found.",
            )

        workspace_dir = os.getcwd()
        result = run_cli_process(
            build_codex_version_command(executable_path=executable),
            cwd=workspace_dir,
            timeout_seconds=min(self.config.timeout_seconds, 5),
        )
        status = _result_version_health_status(self.config, result)
        if status is not None:
            return status

        return adapter_health(
            provider=self.config.provider,
            adapter_kind=self.adapter_id,
            configured=True,
            status="ready",
            error_code=None,
            recovery_hint=None,
            capabilities=["direct_response", "planned_step"],
            message="Codex CLI --version preflight succeeded.",
        )

    def invoke(self, request_payload: AgentRunRequest) -> list[AgentRunEventDraft]:
        if request_payload.run_mode not in {"direct_response", "planned_step"}:
            return self._failure_events(
                "adapter_unsupported_run_mode",
                "codex_cli only supports direct_response and planned_step.",
            )

        events = [
            AgentRunEventDraft(
                type="adapter_preflight_started",
                payload={"adapter_kind": self.adapter_id, "provider": self.config.provider},
            )
        ]
        executable = resolve_executable(self.config.executable_path)
        if executable is None:
            events.extend(
                self._preflight_failure(
                    "adapter_executable_not_found",
                    "Codex CLI executable was not found.",
                    "Install Codex CLI or set AGENTHUB_CODEX_EXECUTABLE.",
                )
            )
            return events

        workspace_dir = workspace_dir_from_request(request_payload)
        if not Path(workspace_dir).exists():
            events.extend(
                self._preflight_failure(
                    "adapter_workspace_missing",
                    "Codex CLI workspace directory does not exist.",
                    "Provide a valid workspace_ref path or use the AgentHub working directory.",
                )
            )
            return events

        events.append(
            AgentRunEventDraft(
                type="adapter_preflight_succeeded",
                payload={
                    "adapter_kind": self.adapter_id,
                    "provider": self.config.provider,
                    "workspace_mode": "read_only",
                },
            )
        )
        prompt = _apply_output_format_instruction(request_payload.instruction)
        if request_payload.run_mode == "planned_step":
            context_bundle = getattr(request_payload, "context_bundle", None) or {}
            prompt = _enrich_prompt_with_context(request_payload.instruction, context_bundle)
        argv = build_codex_direct_response_command(
            executable_path=executable,
            workspace_dir=workspace_dir,
            prompt=prompt,
            prompt_via_stdin=True,
        )
        events.append(
            AgentRunEventDraft(
                type="adapter_process_started",
                payload={
                    "adapter_kind": self.adapter_id,
                    "provider": self.config.provider,
                    "cwd": workspace_dir,
                    "argv_template": codex_direct_response_argv_template(executable),
                    "shell": False,
                },
            )
        )
        result = run_cli_process(
            argv,
            cwd=workspace_dir,
            timeout_seconds=self.config.timeout_seconds,
            stop_after_line=_codex_terminal_stdout_line,
            stdin_text=prompt,
        )
        events.extend(_events_from_codex_result(result))
        return events

    def cancel(self, run_id: str) -> dict[str, object]:
        return {"run_id": run_id, "cancel_requested": False, "message": "codex_cli runs are process-scoped."}

    def _preflight_failure(
        self,
        error_code: str,
        message: str,
        recovery_hint: str,
    ) -> list[AgentRunEventDraft]:
        payload = {
            "error_code": error_code,
            "message": message,
            "provider": self.config.provider,
            "target_agent_id": self.target_agent_id,
            "recovery_hint": recovery_hint,
        }
        return [
            AgentRunEventDraft(type="adapter_preflight_failed", payload=payload),
            AgentRunEventDraft(type="adapter_error", payload=payload),
            AgentRunEventDraft(type="run_failed", payload=payload),
        ]

    def _failure_events(self, error_code: str, message: str) -> list[AgentRunEventDraft]:
        payload = {
            "error_code": error_code,
            "message": message,
            "provider": self.config.provider,
            "target_agent_id": self.target_agent_id,
            "recovery_hint": "Use direct_response or planned_step for Codex CLI in A7-3.",
        }
        return [
            AgentRunEventDraft(type="adapter_error", payload=payload),
            AgentRunEventDraft(type="run_failed", payload=payload),
        ]


def build_codex_direct_response_command(
    *,
    executable_path: str,
    workspace_dir: str,
    prompt: str,
    prompt_via_stdin: bool = False,
) -> list[str]:
    command = [
        executable_path,
        "-a",
        "never",
        "exec",
    ]
    for feature in _codex_disabled_features():
        command.extend(["--disable", feature])
    if _codex_ignore_user_config_enabled():
        command.append("--ignore-user-config")
    command.extend(
        [
            "--json",
            "--cd",
            workspace_dir,
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--color",
            "never",
        ]
    )
    command.append("-" if prompt_via_stdin else prompt)
    return command


def _codex_ignore_user_config_enabled() -> bool:
    value = os.getenv("AGENTHUB_CODEX_IGNORE_USER_CONFIG")
    if value is None:
        value = get_settings().env_value("AGENTHUB_CODEX_IGNORE_USER_CONFIG")
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _codex_disabled_features() -> list[str]:
    value = os.getenv("AGENTHUB_CODEX_DISABLE_FEATURES")
    if value is None:
        value = get_settings().env_value("AGENTHUB_CODEX_DISABLE_FEATURES")
    features: list[str] = []
    for item in str(value or "").split(","):
        feature = item.strip()
        if feature:
            features.append(feature)
    return features


def build_codex_version_command(*, executable_path: str) -> list[str]:
    return [
        executable_path,
        "--version",
    ]


def codex_direct_response_argv_template(executable_path: str = "codex") -> list[str]:
    return build_codex_direct_response_command(
        executable_path=executable_path,
        workspace_dir="<workspace_dir>",
        prompt="<stdin_prompt>",
        prompt_via_stdin=True,
    )


def resolve_executable(executable_path: str | None) -> str | None:
    if not executable_path:
        return None
    clean = executable_path.strip().strip('"').strip("'")
    if any(separator in clean for separator in ("/", "\\")):
        path = Path(clean).expanduser()
        return str(path) if path.exists() else None
    resolved = shutil.which(clean)
    return resolved or None


def workspace_dir_from_request(request_payload: AgentRunRequest) -> str:
    ref = request_payload.workspace_ref or {}
    for field in ("workspace_dir", "path", "root"):
        value = ref.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return os.getcwd()


def _codex_terminal_stdout_line(raw: CliRawLine) -> bool:
    if raw.stream != "stdout":
        return False
    try:
        payload = json.loads(raw.line)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    return str(payload.get("type") or "") in {"turn.completed", "response.completed"}


def _events_from_codex_result(result: CliProcessResult) -> list[AgentRunEventDraft]:
    events: list[AgentRunEventDraft] = []
    final_text: str | None = None
    auth_failure = False
    terminal_failure = False
    terminal_completion = False
    stderr_lines: list[str] = []

    for raw in result.raw_lines:
        if codex_text_has_auth_failure(raw.line):
            auth_failure = True
        if raw.stream == "stdout":
            events.append(AgentRunEventDraft(type="stdout_line", payload={"line": raw.line}))
            parsed = parse_codex_jsonl_line(raw.line)
            if codex_event_has_auth_failure(parsed):
                auth_failure = True
            raw_event = parsed.payload.get("raw_event")
            if isinstance(raw_event, dict) and raw_event.get("type") in {"turn.completed", "response.completed"}:
                terminal_completion = True
            if parsed.type == "assistant_message_completed":
                final_text = str(parsed.payload.get("content_text") or "")
            if parsed.type == "run_failed" and auth_failure:
                parsed = AgentRunEventDraft(
                    type="run_failed",
                    payload={**parsed.payload, "error_code": "backend_auth_failed"},
                )
            if parsed.type == "run_failed":
                terminal_failure = True
                if stderr_lines and "stderr_summary" not in parsed.payload:
                    parsed = AgentRunEventDraft(
                        type="run_failed",
                        payload={**parsed.payload, "stderr_summary": _line_summary(stderr_lines)},
                    )
            events.append(parsed)
        else:
            stderr_lines.append(raw.line)
            events.append(AgentRunEventDraft(type="stderr_line", payload={"line": raw.line}))
            events.append(
                AgentRunEventDraft(
                    type="raw_backend_event",
                    payload={"backend": "codex_cli", "stream": "stderr", "raw_line": raw.line},
                )
            )

    if final_text and (result.exit_code == 0 or terminal_completion):
        events.append(
            AgentRunEventDraft(
                type="run_succeeded",
                payload={"provider": "codex", "adapter_kind": "codex_cli"},
            )
        )
        return events

    if result.timed_out:
        events.append(
            AgentRunEventDraft(
                type="run_timed_out",
                payload={
                    "error_code": "run_timed_out",
                    "message": "Codex CLI direct_response timed out.",
                    "provider": "codex",
                    "recovery_hint": "Reduce prompt size or increase timeout_seconds after verifying CLI health.",
                    "stderr_summary": _line_summary(stderr_lines),
                },
            )
        )
        return events

    if terminal_failure:
        return events

    error_code = "backend_auth_failed" if auth_failure else "adapter_process_failed"
    if result.exit_code == 0:
        error_code = "adapter_invalid_response"
    events.append(
        AgentRunEventDraft(
            type="run_failed",
            payload={
                "error_code": error_code,
                "message": "Codex CLI exited without final assistant output.",
                "provider": "codex",
                "recovery_hint": "Inspect Codex JSONL output and CLI authentication.",
                "exit_code": result.exit_code,
                "stderr_summary": _line_summary(stderr_lines),
            },
        )
    )
    return events


def _line_summary(lines: list[str], *, limit: int = 800) -> str | None:
    text = "\n".join(line.strip() for line in lines if line.strip()).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _result_health_status(config: ProviderConfig, result: CliProcessResult) -> AdapterHealth | None:
    events = _events_from_codex_result(result)
    auth_failure = any(codex_event_has_auth_failure(event) for event in events)
    succeeded = any(event.type == "run_succeeded" for event in events)
    if succeeded:
        return None
    if auth_failure:
        return adapter_health(
            provider=config.provider,
            adapter_kind="codex_cli",
            configured=False,
            status="missing_credentials",
            error_code="backend_auth_failed",
            recovery_hint="Run codex login or configure Codex credentials before starting AgentHub runs.",
            capabilities=[],
            message="Codex CLI authentication failed during direct_response probe.",
        )
    if result.timed_out:
        return adapter_health(
            provider=config.provider,
            adapter_kind="codex_cli",
            configured=False,
            status="unavailable",
            error_code="adapter_timeout",
            recovery_hint="Codex CLI direct_response probe timed out.",
            capabilities=[],
            message="Codex CLI did not complete the direct_response probe before timeout.",
        )
    return adapter_health(
        provider=config.provider,
        adapter_kind="codex_cli",
        configured=False,
        status="unavailable",
        error_code="adapter_process_failed",
        recovery_hint="Inspect Codex CLI installation, authentication, and network availability.",
        capabilities=[],
        message="Codex CLI direct_response probe failed.",
    )


def _result_version_health_status(config: ProviderConfig, result: CliProcessResult) -> AdapterHealth | None:
    combined_output = "\n".join([*result.stdout_lines, *result.stderr_lines])
    if codex_text_has_auth_failure(combined_output):
        return adapter_health(
            provider=config.provider,
            adapter_kind="codex_cli",
            configured=False,
            status="missing_credentials",
            error_code="backend_auth_failed",
            recovery_hint="Run codex login or configure Codex credentials before starting AgentHub runs.",
            capabilities=[],
            message="Codex CLI authentication failed during --version preflight.",
        )
    if result.timed_out:
        return adapter_health(
            provider=config.provider,
            adapter_kind="codex_cli",
            configured=False,
            status="unavailable",
            error_code="adapter_timeout",
            recovery_hint="Codex CLI --version timed out.",
            capabilities=[],
            message="Codex CLI did not complete the lightweight preflight before timeout.",
        )
    if result.exit_code == 0:
        return None
    return adapter_health(
        provider=config.provider,
        adapter_kind="codex_cli",
        configured=False,
        status="unavailable",
        error_code="adapter_process_failed",
        recovery_hint="Inspect Codex CLI installation and PATH configuration.",
        capabilities=[],
        message="Codex CLI --version preflight failed.",
    )
