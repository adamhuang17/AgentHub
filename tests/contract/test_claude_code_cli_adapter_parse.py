from pathlib import Path

from services.api.app.agents.adapters.claude_code_cli import (
    CLAUDE_CODE_REAL_CLI_ENV,
    ClaudeCodeCliAdapter,
    _events_from_claude_result,
)
from services.api.app.agents.adapters.cli_process import CliProcessResult, CliRawLine
from services.api.app.agents.adapters.parsers.claude_stream_json import parse_claude_stream_json_line
from services.api.app.agents.provider_config import validate_provider_config


def test_claude_system_init_maps_backend_session_started():
    event = parse_claude_stream_json_line(
        '{"type":"system","subtype":"init","cwd":"D:/AgentHub","session_id":"s1",'
        '"model":"claude","tools":[],"mcp_servers":[],"apiKeySource":"none",'
        '"claude_code_version":"2.1.170"}'
    )

    assert event.type == "backend_session_started"
    assert event.payload["cwd"] == "D:/AgentHub"
    assert event.payload["tools"] == []
    assert event.payload["mcp_servers"] == []
    assert event.payload["apiKeySource"] == "none"


def test_claude_api_retry_maps_backend_retry():
    event = parse_claude_stream_json_line('{"type":"system","subtype":"api_retry","message":"retrying"}')

    assert event.type == "backend_retry"
    assert "retry" in event.payload["message"]


def test_claude_result_maps_assistant_message_completed():
    event = parse_claude_stream_json_line('{"type":"result","subtype":"success","result":"hello"}')

    assert event.type == "assistant_message_completed"
    assert event.payload["content_text"] == "hello"


def test_claude_timeout_maps_run_timed_out():
    result = CliProcessResult(
        argv=["claude"],
        cwd="D:/AgentHub",
        exit_code=None,
        stdout_lines=['{"type":"system","subtype":"api_retry","message":"retrying"}'],
        stderr_lines=[],
        raw_lines=[CliRawLine(stream="stdout", line='{"type":"system","subtype":"api_retry","message":"retrying"}')],
        timed_out=True,
        duration_seconds=1.0,
    )

    events = _events_from_claude_result(result)

    assert any(event.type == "backend_retry" for event in events)
    assert any(event.type == "run_timed_out" for event in events)
    assert not any(event.type == "assistant_message_completed" for event in events)


def test_claude_non_zero_exit_without_final_does_not_create_assistant_message():
    result = CliProcessResult(
        argv=["claude"],
        cwd="D:/AgentHub",
        exit_code=1,
        stdout_lines=['{"type":"system","subtype":"init","tools":[],"mcp_servers":[]}'],
        stderr_lines=["failed"],
        raw_lines=[
            CliRawLine(stream="stdout", line='{"type":"system","subtype":"init","tools":[],"mcp_servers":[]}'),
            CliRawLine(stream="stderr", line="failed"),
        ],
        timed_out=False,
        duration_seconds=1.0,
    )

    events = _events_from_claude_result(result)

    assert any(event.type == "run_failed" for event in events)
    assert not any(event.type == "assistant_message_completed" for event in events)
    assert not any(event.type == "run_succeeded" for event in events)


def test_claude_default_runtime_disabled_returns_timeout_without_process(monkeypatch):
    monkeypatch.delenv(CLAUDE_CODE_REAL_CLI_ENV, raising=False)
    monkeypatch.setattr("services.api.app.agents.adapters.claude_code_cli.resolve_executable", lambda _: "claude")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Claude Code process should not start while real CLI runtime is disabled.")

    monkeypatch.setattr("services.api.app.agents.adapters.claude_code_cli.run_cli_process", fail_if_called)
    adapter = ClaudeCodeCliAdapter(config=_claude_config())

    health = adapter.health()
    assert health.configured is False
    assert health.error_code == "adapter_timeout"

    events = adapter.invoke(_request())
    event_types = [event.type for event in events]

    assert event_types == ["adapter_preflight_started", "adapter_preflight_succeeded", "run_timed_out"]
    assert events[-1].payload["error_code"] == "run_timed_out"
    assert events[-1].payload["manual_retry_env"] == CLAUDE_CODE_REAL_CLI_ENV


def test_claude_manual_runtime_enable_starts_process(monkeypatch):
    monkeypatch.setenv(CLAUDE_CODE_REAL_CLI_ENV, "1")
    monkeypatch.setattr("services.api.app.agents.adapters.claude_code_cli.resolve_executable", lambda _: "claude")

    def fake_run_cli_process(*args, **kwargs):
        return CliProcessResult(
            argv=["claude"],
            cwd=str(Path.cwd()),
            exit_code=0,
            stdout_lines=['{"type":"result","subtype":"success","result":"hello"}'],
            stderr_lines=[],
            raw_lines=[
                CliRawLine(stream="stdout", line='{"type":"result","subtype":"success","result":"hello"}')
            ],
            timed_out=False,
            duration_seconds=0.1,
        )

    monkeypatch.setattr("services.api.app.agents.adapters.claude_code_cli.run_cli_process", fake_run_cli_process)
    events = ClaudeCodeCliAdapter(config=_claude_config()).invoke(_request())
    event_types = [event.type for event in events]

    assert "adapter_process_started" in event_types
    assert "assistant_message_completed" in event_types
    assert "run_succeeded" in event_types


def _claude_config():
    return validate_provider_config(
        {
            "provider": "anthropic",
            "adapter_kind": "claude_code_cli",
            "backend_type": "coding_agent_backend",
            "api_base": None,
            "model": None,
            "credential_source": None,
            "executable_path": "claude",
            "timeout_seconds": 1,
            "max_output_tokens": 128,
            "temperature": 0.2,
            "workspace_mode": "read_only",
            "allowed_tools": [],
            "health_check_strategy": "direct_probe",
        }
    )


def _request():
    return type(
        "Request",
        (),
        {
            "run_mode": "direct_response",
            "instruction": "hello",
            "workspace_ref": {"workspace_dir": str(Path.cwd())},
            "context_bundle": {},
        },
    )()
