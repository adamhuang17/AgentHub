from services.api.app.agents.adapters.parsers.codex_jsonl import parse_codex_jsonl_line
from services.api.app.agents.adapters.cli_process import CliProcessResult, CliRawLine
from services.api.app.agents.adapters.codex_cli import (
    CodexCliAdapter,
    _events_from_codex_result,
    _result_health_status,
    _result_version_health_status,
)
from services.api.app.agents.provider_config import validate_provider_config


def _codex_config():
    return validate_provider_config(
        {
            "provider": "codex",
            "adapter_kind": "codex_cli",
            "backend_type": "coding_agent_backend",
            "api_base": None,
            "model": None,
            "credential_source": None,
            "executable_path": "codex",
            "timeout_seconds": 10,
            "max_output_tokens": 128,
            "temperature": 0.2,
            "workspace_mode": "read_only",
            "allowed_tools": [],
            "health_check_strategy": "direct_probe",
        }
    )


def test_codex_thread_started_maps_backend_session_started():
    event = parse_codex_jsonl_line('{"type":"thread.started","thread_id":"thread-1"}')

    assert event.type == "backend_session_started"
    assert event.payload["thread_id"] == "thread-1"


def test_codex_401_missing_bearer_maps_backend_auth_failed():
    event = parse_codex_jsonl_line(
        '{"type":"error","message":"Reconnecting after 401 Unauthorized: Missing bearer token"}'
    )

    assert event.type == "adapter_error"
    assert event.payload["error_code"] == "backend_auth_failed"


def test_codex_turn_failed_maps_run_failed():
    event = parse_codex_jsonl_line('{"type":"turn.failed","error":{"message":"stream disconnected"}}')

    assert event.type == "run_failed"
    assert event.payload["error_code"] == "adapter_process_failed"


def test_codex_unknown_jsonl_is_preserved_as_raw_backend_event():
    event = parse_codex_jsonl_line('{"type":"new.future.event","value":true}')

    assert event.type == "raw_backend_event"
    assert event.payload["raw_event"]["type"] == "new.future.event"


def test_codex_invalid_json_line_does_not_create_fake_success():
    event = parse_codex_jsonl_line("{not json")

    assert event.type == "raw_backend_event"
    assert event.payload["error_code"] == "adapter_invalid_json"
    assert event.type != "assistant_message_completed"
    assert event.type != "run_succeeded"


def test_codex_stderr_auth_text_maps_backend_auth_failed_without_fake_success():
    result = CliProcessResult(
        argv=["codex"],
        cwd="D:/AgentHub",
        exit_code=1,
        stdout_lines=[],
        stderr_lines=["401 Unauthorized: Missing bearer token"],
        raw_lines=[CliRawLine(stream="stderr", line="401 Unauthorized: Missing bearer token")],
        timed_out=False,
        duration_seconds=1.0,
    )

    events = _events_from_codex_result(result)

    assert any(event.type == "stderr_line" for event in events)
    assert any(event.type == "raw_backend_event" for event in events)
    assert any(event.type == "run_failed" and event.payload["error_code"] == "backend_auth_failed" for event in events)
    assert not any(event.type == "assistant_message_completed" for event in events)
    assert not any(event.type == "run_succeeded" for event in events)


def test_codex_explicit_final_assistant_output_maps_completed():
    event = parse_codex_jsonl_line(
        '{"type":"item.completed","item":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"done"}]}}'
    )

    assert event.type == "assistant_message_completed"
    assert event.payload["content_text"] == "done"


def test_codex_agent_message_item_maps_completed():
    event = parse_codex_jsonl_line(
        '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"AgentHub Codex direct response works."}}'
    )

    assert event.type == "assistant_message_completed"
    assert event.payload["content_text"] == "AgentHub Codex direct response works."


def test_result_health_status_returns_none_on_success():
    result = CliProcessResult(
        argv=["codex"],
        cwd="D:/AgentHub",
        exit_code=0,
        stdout_lines=['{"type":"item.completed","item":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"done"}]}}'],
        stderr_lines=[],
        raw_lines=[CliRawLine(stream="stdout", line='{"type":"item.completed","item":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"done"}]}}')],
        timed_out=False,
        duration_seconds=0.5,
    )
    assert _result_health_status(_codex_config(), result) is None


def test_result_health_status_returns_auth_failure_on_401():
    result = CliProcessResult(
        argv=["codex"],
        cwd="D:/AgentHub",
        exit_code=1,
        stdout_lines=[],
        stderr_lines=["401 Unauthorized: Missing bearer token"],
        raw_lines=[CliRawLine(stream="stderr", line="401 Unauthorized: Missing bearer token")],
        timed_out=False,
        duration_seconds=1.0,
    )
    health = _result_health_status(_codex_config(), result)
    assert health is not None
    assert health.status == "missing_credentials"
    assert health.error_code == "backend_auth_failed"


def test_result_health_status_returns_timeout_on_timed_out():
    result = CliProcessResult(
        argv=["codex"],
        cwd="D:/AgentHub",
        exit_code=None,
        stdout_lines=[],
        stderr_lines=[],
        raw_lines=[],
        timed_out=True,
        duration_seconds=10.0,
    )
    health = _result_health_status(_codex_config(), result)
    assert health is not None
    assert health.status == "unavailable"
    assert health.error_code == "adapter_timeout"


def test_codex_completed_turn_succeeds_even_if_process_is_later_terminated():
    result = CliProcessResult(
        argv=["codex"],
        cwd="D:/AgentHub",
        exit_code=1,
        stdout_lines=[
            '{"type":"thread.started","thread_id":"t1"}',
            '{"type":"turn.started"}',
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"done"}}',
            '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}',
        ],
        stderr_lines=["Reading additional input from stdin..."],
        raw_lines=[
            CliRawLine(stream="stdout", line='{"type":"thread.started","thread_id":"t1"}'),
            CliRawLine(stream="stdout", line='{"type":"turn.started"}'),
            CliRawLine(stream="stdout", line='{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"done"}}'),
            CliRawLine(stream="stdout", line='{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}'),
            CliRawLine(stream="stderr", line="Reading additional input from stdin..."),
        ],
        timed_out=False,
        duration_seconds=1.0,
        terminated_early=True,
    )

    events = _events_from_codex_result(result)
    event_types = [event.type for event in events]

    assert "assistant_message_completed" in event_types
    assert "run_succeeded" in event_types
    assert "run_timed_out" not in event_types
    assert not any(event.type == "run_failed" for event in events)


def test_result_health_status_returns_process_failed_on_generic_error():
    result = CliProcessResult(
        argv=["codex"],
        cwd="D:/AgentHub",
        exit_code=1,
        stdout_lines=["some output"],
        stderr_lines=["error"],
        raw_lines=[CliRawLine(stream="stdout", line="some output"), CliRawLine(stream="stderr", line="error")],
        timed_out=False,
        duration_seconds=1.0,
    )
    health = _result_health_status(_codex_config(), result)
    assert health is not None
    assert health.status == "unavailable"
    assert health.error_code == "adapter_process_failed"


def test_result_version_health_status_returns_none_on_version_success():
    result = CliProcessResult(
        argv=["codex", "--version"],
        cwd="D:/AgentHub",
        exit_code=0,
        stdout_lines=["codex-cli 0.139.0"],
        stderr_lines=[],
        raw_lines=[CliRawLine(stream="stdout", line="codex-cli 0.139.0")],
        timed_out=False,
        duration_seconds=0.2,
    )

    assert _result_version_health_status(_codex_config(), result) is None


def test_result_version_health_status_returns_timeout_on_version_timeout():
    result = CliProcessResult(
        argv=["codex", "--version"],
        cwd="D:/AgentHub",
        exit_code=None,
        stdout_lines=[],
        stderr_lines=[],
        raw_lines=[],
        timed_out=True,
        duration_seconds=5.0,
    )

    health = _result_version_health_status(_codex_config(), result)

    assert health is not None
    assert health.status == "unavailable"
    assert health.error_code == "adapter_timeout"


def test_result_version_health_status_returns_process_failed_on_nonzero_exit():
    result = CliProcessResult(
        argv=["codex", "--version"],
        cwd="D:/AgentHub",
        exit_code=1,
        stdout_lines=[],
        stderr_lines=["not runnable"],
        raw_lines=[CliRawLine(stream="stderr", line="not runnable")],
        timed_out=False,
        duration_seconds=0.2,
    )

    health = _result_version_health_status(_codex_config(), result)

    assert health is not None
    assert health.status == "unavailable"
    assert health.error_code == "adapter_process_failed"


def test_codex_adapter_health_uses_lightweight_version_preflight(monkeypatch):
    captured = {}

    def fake_run_cli_process(argv, *, cwd, timeout_seconds):
        captured["argv"] = list(argv)
        captured["cwd"] = str(cwd)
        captured["timeout_seconds"] = timeout_seconds
        return CliProcessResult(
            argv=list(argv),
            cwd=str(cwd),
            exit_code=0,
            stdout_lines=["codex-cli 0.139.0"],
            stderr_lines=[],
            raw_lines=[CliRawLine(stream="stdout", line="codex-cli 0.139.0")],
            timed_out=False,
            duration_seconds=0.2,
        )

    monkeypatch.setattr("services.api.app.agents.adapters.codex_cli.resolve_executable", lambda _: "codex")
    monkeypatch.setattr("services.api.app.agents.adapters.codex_cli.run_cli_process", fake_run_cli_process)

    health = CodexCliAdapter(config=_codex_config(), target_agent_id="agent-codex").health()

    assert captured["argv"] == ["codex", "--version"]
    assert captured["timeout_seconds"] == 5
    assert health.configured is True
    assert health.status == "ready"
    assert health.message == "Codex CLI --version preflight succeeded."


def test_codex_direct_response_passes_raw_instruction_without_context(monkeypatch, tmp_path):
    captured = {}

    def fake_run_cli_process(argv, *, cwd, timeout_seconds, **kwargs):
        captured["argv"] = list(argv)
        captured["stop_after_line"] = kwargs.get("stop_after_line")
        captured["stdin_text"] = kwargs.get("stdin_text")
        return CliProcessResult(
            argv=list(argv),
            cwd=str(cwd),
            exit_code=0,
            stdout_lines=['{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}'],
            stderr_lines=[],
            raw_lines=[CliRawLine(stream="stdout", line='{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}')],
            timed_out=False,
            duration_seconds=0.2,
        )

    monkeypatch.setenv("AGENTHUB_CODEX_IGNORE_USER_CONFIG", "0")
    monkeypatch.setenv("AGENTHUB_CODEX_DISABLE_FEATURES", "")
    monkeypatch.setattr("services.api.app.agents.adapters.codex_cli.resolve_executable", lambda _: "codex")
    monkeypatch.setattr("services.api.app.agents.adapters.codex_cli.run_cli_process", fake_run_cli_process)

    request = type(
        "Request",
        (),
        {
            "run_mode": "direct_response",
            "instruction": "raw user message",
            "workspace_ref": {"workspace_dir": str(tmp_path)},
            "context_bundle": {
                "recent_messages": [
                    {"sender_type": "user", "text": "must not be prepended"},
                ],
            },
        },
    )()

    events = CodexCliAdapter(config=_codex_config(), target_agent_id="agent-codex").invoke(request)

    assert captured["argv"][-1] == "-"
    assert "[AgentHub output format]" in captured["stdin_text"]
    assert "[User instruction]\nraw user message" in captured["stdin_text"]
    assert captured["stop_after_line"] is not None
    assert "[Recent conversation]" not in captured["stdin_text"]
    assert any(event.type == "run_succeeded" for event in events)
