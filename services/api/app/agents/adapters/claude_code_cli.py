from __future__ import annotations

import os
from pathlib import Path

from services.api.app.agent_runs.schema import AgentRunEventDraft, AgentRunRequest
from services.api.app.agents.adapter_health import AdapterHealth, adapter_health
from services.api.app.agents.adapters.cli_process import CliProcessResult, run_cli_process
from services.api.app.agents.adapters.codex_cli import resolve_executable, workspace_dir_from_request
from services.api.app.agents.adapters.parsers.claude_stream_json import parse_claude_stream_json_line
from services.api.app.agents.provider_config import ProviderConfig
from services.api.app.memory.prompt_context import enrich_cli_prompt as _enrich_prompt_with_context


CLAUDE_CODE_REAL_CLI_ENV = "AGENTHUB_ENABLE_CLAUDE_CODE_REAL_CLI"


def _claude_subprocess_env() -> dict[str, str] | None:
    """Build env for the claude subprocess, overriding ANTHROPIC_* from config.

    The Windows system ANTHROPIC_BASE_URL/AUTH_TOKEN may point at a dead host;
    AGENTHUB_CLAUDE_ANTHROPIC_* (set in .env) override them so claude reaches GLM.
    Returns None when no overrides are configured (subprocess inherits os.environ).
    """
    overrides = {
        "ANTHROPIC_BASE_URL": os.getenv("AGENTHUB_CLAUDE_ANTHROPIC_BASE_URL"),
        "ANTHROPIC_AUTH_TOKEN": os.getenv("AGENTHUB_CLAUDE_ANTHROPIC_AUTH_TOKEN"),
        "ANTHROPIC_DEFAULT_OPUS_MODEL": os.getenv("AGENTHUB_CLAUDE_DEFAULT_OPUS_MODEL"),
        "ANTHROPIC_DEFAULT_SONNET_MODEL": os.getenv("AGENTHUB_CLAUDE_DEFAULT_SONNET_MODEL"),
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": os.getenv("AGENTHUB_CLAUDE_DEFAULT_HAIKU_MODEL"),
    }
    if not any(overrides.values()):
        return None
    env = dict(os.environ)
    for key, value in overrides.items():
        if value:
            env[key] = value
    return env


class ClaudeCodeCliAdapter:
    adapter_id = "claude_code_cli"

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
                recovery_hint="Install Claude Code CLI or set AGENTHUB_CLAUDE_CODE_EXECUTABLE.",
                capabilities=[],
                message="Claude Code CLI executable was not found.",
            )

        if not _real_cli_runtime_enabled():
            return adapter_health(
                provider=self.config.provider,
                adapter_kind=self.adapter_id,
                configured=False,
                status="unavailable",
                error_code="adapter_timeout",
                recovery_hint=f"Set {CLAUDE_CODE_REAL_CLI_ENV}=1 to manually retry the real Claude Code CLI runtime.",
                capabilities=[],
                message="Claude Code real CLI runtime is disabled by default; direct_response returns timeout.",
            )

        workspace_dir = str(Path.cwd())
        result = run_cli_process(
            build_claude_direct_response_command(executable_path=executable, prompt="Reply with OK."),
            cwd=workspace_dir,
            timeout_seconds=min(self.config.timeout_seconds, 10),
            env=_claude_subprocess_env(),
        )
        status = _result_health_status(self.config, result)
        if status is not None:
            return status

        return adapter_health(
            provider=self.config.provider,
            adapter_kind=self.adapter_id,
            configured=True,
            status="ready",
            error_code=None,
            recovery_hint=None,
            capabilities=["direct_response"],
            message="Claude Code direct_response probe succeeded.",
        )

    def invoke(self, request_payload: AgentRunRequest) -> list[AgentRunEventDraft]:
        if request_payload.run_mode != "direct_response":
            return self._failure_events("adapter_unsupported_run_mode", "claude_code_cli only supports direct_response.")

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
                    "Claude Code CLI executable was not found.",
                    "Install Claude Code CLI or set AGENTHUB_CLAUDE_CODE_EXECUTABLE.",
                )
            )
            return events

        workspace_dir = workspace_dir_from_request(request_payload)
        if not Path(workspace_dir).exists():
            events.extend(
                self._preflight_failure(
                    "adapter_workspace_missing",
                    "Claude Code CLI workspace directory does not exist.",
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
                    "tools": [],
                    "mcp_servers": [],
                    "real_cli_runtime_enabled": _real_cli_runtime_enabled(),
                },
            )
        )
        if not _real_cli_runtime_enabled():
            events.append(_manual_timeout_event())
            return events

        context_bundle = getattr(request_payload, "context_bundle", None) or {}
        context_enriched_prompt = _enrich_prompt_with_context(request_payload.instruction, context_bundle)
        argv = build_claude_direct_response_command(
            executable_path=executable,
            prompt=context_enriched_prompt,
        )
        events.append(
            AgentRunEventDraft(
                type="adapter_process_started",
                payload={
                    "adapter_kind": self.adapter_id,
                    "provider": self.config.provider,
                    "cwd": workspace_dir,
                    "argv_template": claude_direct_response_argv_template(executable),
                    "shell": False,
                },
            )
        )
        result = run_cli_process(
            argv,
            cwd=workspace_dir,
            timeout_seconds=self.config.timeout_seconds,
            env=_claude_subprocess_env(),
        )
        events.extend(_events_from_claude_result(result))
        return events

    def cancel(self, run_id: str) -> dict[str, object]:
        return {"run_id": run_id, "cancel_requested": False, "message": "claude_code_cli runs are process-scoped."}

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
            "recovery_hint": "Use direct_response for Claude Code CLI in A7-3.",
        }
        return [
            AgentRunEventDraft(type="adapter_error", payload=payload),
            AgentRunEventDraft(type="run_failed", payload=payload),
        ]


def build_claude_direct_response_command(
    *,
    executable_path: str,
    prompt: str,
) -> list[str]:
    return [
        executable_path,
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--tools=",
        "--strict-mcp-config",
    ]


def claude_direct_response_argv_template(executable_path: str = "claude") -> list[str]:
    return build_claude_direct_response_command(executable_path=executable_path, prompt="<prompt>")


def _real_cli_runtime_enabled() -> bool:
    return os.getenv(CLAUDE_CODE_REAL_CLI_ENV) == "1"


def _manual_timeout_event() -> AgentRunEventDraft:
    return AgentRunEventDraft(
        type="run_timed_out",
        payload={
            "error_code": "run_timed_out",
            "message": "Claude Code direct_response timed out because real CLI runtime is disabled by default.",
            "provider": "anthropic",
            "recovery_hint": f"Set {CLAUDE_CODE_REAL_CLI_ENV}=1 after Claude Code is usable, then retry.",
            "backend_retry_seen": False,
            "manual_retry_env": CLAUDE_CODE_REAL_CLI_ENV,
        },
    )


def _events_from_claude_result(result: CliProcessResult) -> list[AgentRunEventDraft]:
    events: list[AgentRunEventDraft] = []
    final_text: str | None = None
    retry_seen = False
    unsafe_tools = False
    terminal_failure = False
    stderr_lines: list[str] = []

    for raw in result.raw_lines:
        if raw.stream == "stdout":
            events.append(AgentRunEventDraft(type="stdout_line", payload={"line": raw.line}))
            parsed = parse_claude_stream_json_line(raw.line)
            if parsed.type == "backend_retry":
                retry_seen = True
            if parsed.type == "backend_session_started":
                tools = parsed.payload.get("tools")
                mcp_servers = parsed.payload.get("mcp_servers")
                unsafe_tools = unsafe_tools or bool(tools) or bool(mcp_servers)
            if parsed.type == "assistant_message_completed":
                final_text = str(parsed.payload.get("content_text") or "")
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

    if result.timed_out:
        events.append(
            AgentRunEventDraft(
                type="run_timed_out",
                payload={
                    "error_code": "run_timed_out",
                    "message": "Claude Code direct_response timed out.",
                    "provider": "anthropic",
                    "recovery_hint": "Inspect Claude Code auth and reduce timeout retry loops before retrying.",
                    "backend_retry_seen": retry_seen,
                    "stderr_summary": _line_summary(stderr_lines),
                },
            )
        )
        return events

    if unsafe_tools:
        events.append(
            AgentRunEventDraft(
                type="run_failed",
                payload={
                    "error_code": "adapter_unsafe_tools_enabled",
                    "message": "Claude Code direct_response reported enabled tools or MCP servers.",
                    "provider": "anthropic",
                    "recovery_hint": "Keep --tools= and --strict-mcp-config enabled for direct_response.",
                },
            )
        )
        return events

    if terminal_failure:
        return events

    if final_text and result.exit_code == 0:
        events.append(
            AgentRunEventDraft(
                type="run_succeeded",
                payload={"provider": "anthropic", "adapter_kind": "claude_code_cli"},
            )
        )
        return events

    error_code = "adapter_auth_unusable" if retry_seen else "adapter_process_failed"
    if result.exit_code == 0:
        error_code = "adapter_invalid_response"
    events.append(
        AgentRunEventDraft(
            type="run_failed",
            payload={
                "error_code": error_code,
                "message": "Claude Code exited without final assistant output.",
                "provider": "anthropic",
                "recovery_hint": "Inspect Claude Code stream-json output and authentication status.",
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
    events = _events_from_claude_result(result)
    succeeded = any(event.type == "run_succeeded" for event in events)
    retry_seen = any(event.type == "backend_retry" for event in events)
    unsafe_tools = any(
        event.type == "run_failed" and event.payload.get("error_code") == "adapter_unsafe_tools_enabled"
        for event in events
    )
    if succeeded:
        return None
    if unsafe_tools:
        return adapter_health(
            provider=config.provider,
            adapter_kind="claude_code_cli",
            configured=False,
            status="unavailable",
            error_code="adapter_unsafe_tools_enabled",
            recovery_hint="Keep --tools= and --strict-mcp-config enabled for direct_response.",
            capabilities=[],
            message="Claude Code direct_response probe reported enabled tools.",
        )
    if retry_seen or any(event.type == "run_timed_out" for event in events):
        return adapter_health(
            provider=config.provider,
            adapter_kind="claude_code_cli",
            configured=False,
            status="missing_credentials" if retry_seen else "unavailable",
            error_code="adapter_auth_unusable" if retry_seen else "adapter_timeout",
            recovery_hint="Claude Code auth status is not sufficient; verify non-interactive stream-json works.",
            capabilities=[],
            message="Claude Code direct_response probe did not complete successfully.",
        )
    return adapter_health(
        provider=config.provider,
        adapter_kind="claude_code_cli",
        configured=False,
        status="unavailable",
        error_code="adapter_process_failed",
        recovery_hint="Inspect Claude Code CLI installation, authentication, and network availability.",
        capabilities=[],
        message="Claude Code direct_response probe failed.",
    )
