import json
import os
import uuid

import pytest

from services.api.app.agent_runs.repository import list_run_events
from services.api.app.agent_runs.service import create_run_from_body
from services.api.app.agents.adapter_registry import AdapterRegistry
from services.api.app.agents.adapters.claude_code_cli import (
    CLAUDE_CODE_REAL_CLI_ENV,
    ClaudeCodeCliAdapter,
    build_claude_direct_response_command,
)
from services.api.app.agents.adapters.cli_process import CliProcessResult, CliRawLine
from services.api.app.agents.adapters.codex_cli import (
    _events_from_codex_result,
    build_codex_direct_response_command,
    resolve_executable,
)
from services.api.app.agents.adapters.parsers.claude_stream_json import parse_claude_stream_json_line
from services.api.app.agents.repository import get_agents_by_ids
from services.api.app.agents.provider_config import CUSTOM_OPENAI_PROVIDER_KEYS
from services.api.app.agents.provider_config import validate_provider_config
from services.api.app.conversations.repository import create_conversation, create_message, list_messages
from services.api.app.shared.database import connect
from services.api.app.shared.time import utc_now


_PROVIDER_CASES = {
    "qwen_turbo": {
        "agent_id": "qwen_turbo_agent",
        "api_base_env": "AGENTHUB_PROVIDER_QWEN_API_BASE",
        "model_env": "AGENTHUB_PROVIDER_QWEN_MODEL",
        "credential_env": "AGENTHUB_PROVIDER_QWEN_API_KEY",
    },
    "volc_deepseek_flash": {
        "agent_id": "volc_deepseek_flash_agent",
        "api_base_env": "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_BASE",
        "model_env": "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_FLASH_MODEL",
        "credential_env": "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_KEY",
    },
    "volc_deepseek_pro": {
        "agent_id": "volc_deepseek_pro_agent",
        "api_base_env": "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_BASE",
        "model_env": "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_PRO_MODEL",
        "credential_env": "AGENTHUB_PROVIDER_VOLC_DEEPSEEK_API_KEY",
    },
    "deepseek_official": {
        "agent_id": "deepseek_official_agent",
        "api_base_env": "AGENTHUB_PROVIDER_DEEPSEEK_API_BASE",
        "model_env": "AGENTHUB_PROVIDER_DEEPSEEK_MODEL",
        "credential_env": "AGENTHUB_PROVIDER_DEEPSEEK_API_KEY",
    },
}


def _test_run_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _real_cli_path(env_name, label):
    if os.getenv("AGENTHUB_RUN_REAL_CLI_TESTS") != "1":
        pytest.skip("requires AGENTHUB_RUN_REAL_CLI_TESTS=1")
    configured = os.getenv(env_name)
    if not configured:
        pytest.skip(f"requires non-secret env {env_name}")
    resolved = resolve_executable(configured)
    if resolved is None:
        pytest.skip(f"{label} executable from {env_name} was not found or executable")
    return resolved


def _insert_agent(agent_id, *, provider, configured=True, execution_enabled=True, health_status=None):
    now = utc_now()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO agents (
                id, name, provider, avatar, initials, capability_tags_json,
                execution_enabled, configured, health_status,
                enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, NULL, 'A7', '["direct_response","chat","model"]', ?, ?, ?, 1, ?, ?)
            """,
            (
                agent_id,
                f"{agent_id} Agent",
                provider,
                1 if execution_enabled else 0,
                1 if configured else 0,
                health_status or ("configured" if configured else "profile_only"),
                now,
                now,
            ),
        )


def _conversation_and_message(agent_id, test_run_id):
    conversation = create_conversation(
        title=f"{test_run_id} conversation",
        mode="private_agent",
        agent_ids=[agent_id],
        test_run_id=test_run_id,
    )
    message = create_message(
        conversation_id=str(conversation["id"]),
        message_type="text",
        content={"text": "A7 direct response real adapter check."},
        mentions=[],
        references=[],
        reply_to_id=None,
        test_run_id=test_run_id,
    )
    return conversation, message


def _run_payload(provider_key, agent_id, message, instruction):
    del provider_key
    return {
        "source_type": "message",
        "source_message_id": message["id"],
        "target_agent_id": agent_id,
        "run_mode": "direct_response",
        "instruction": instruction,
        "context_bundle": {},
        "workspace_ref": None,
        "allowed_tools": [],
        "expected_artifacts": [],
    }


def _assert_no_task_plan_step_records(conversation_id, test_run_id):
    with connect() as connection:
        task_count = connection.execute(
            "SELECT COUNT(*) AS count FROM tasks WHERE conversation_id = ? AND test_run_id = ?",
            (conversation_id, test_run_id),
        ).fetchone()["count"]
        plan_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM plans p
            JOIN tasks t ON t.id = p.task_id
            WHERE t.conversation_id = ? AND p.test_run_id = ?
            """,
            (conversation_id, test_run_id),
        ).fetchone()["count"]
        step_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM plan_steps ps
            JOIN plans p ON p.id = ps.plan_id
            JOIN tasks t ON t.id = p.task_id
            WHERE t.conversation_id = ? AND t.test_run_id = ?
            """,
            (conversation_id, test_run_id),
        ).fetchone()["count"]

    assert task_count == 0
    assert plan_count == 0
    assert step_count == 0


def _assert_no_artifact_diff_deploy_records(test_run_id):
    candidate_tables = (
        "artifacts",
        "artifact_versions",
        "diffs",
        "patches",
        "deployments",
        "deployment_releases",
    )
    with connect() as connection:
        for table in candidate_tables:
            exists = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if exists is None:
                continue
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            if "test_run_id" not in columns:
                continue
            count = connection.execute(
                f"SELECT COUNT(*) AS count FROM {table} WHERE test_run_id = ?",
                (test_run_id,),
            ).fetchone()["count"]
            assert count == 0


def _assert_env_secrets_not_leaked(payload, env_names):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    for env_name in env_names:
        secret = os.getenv(env_name)
        if secret and secret in encoded:
            pytest.fail(f"{env_name} leaked into serialized payload")


def _event_types(run_id, test_run_id):
    return [event["type"] for event in list_run_events(str(run_id), test_run_id=test_run_id)]


def _assert_no_assistant_message(conversation_id, test_run_id):
    messages = list_messages(str(conversation_id), test_run_id=test_run_id)
    assert [message["sender_type"] for message in messages].count("assistant") == 0
    return messages


def _provider_agent_profile(agent_id, provider_key):
    return {
        "id": agent_id,
        "provider": provider_key,
        "configured": True,
        "execution_enabled": True,
        "health_status": "configured",
        "capability_tags": ["direct_response", "chat", "model"],
    }


def _assert_provider_agent_shape(agent_id, provider_key):
    agents = get_agents_by_ids([agent_id])
    assert len(agents) == 1
    agent = agents[0]
    assert agent["provider"] == provider_key
    assert agent["execution_enabled"] is True
    assert {"direct_response", "chat", "model"}.issubset(set(agent["capability_tags"]))


def _real_provider_env_complete(provider_key):
    case = _PROVIDER_CASES[provider_key]
    env_names = (case["api_base_env"], case["model_env"], case["credential_env"])
    return os.getenv("AGENTHUB_RUN_REAL_PROVIDER_TESTS") == "1" and all(os.getenv(name) for name in env_names)


@pytest.mark.parametrize("provider_key", CUSTOM_OPENAI_PROVIDER_KEYS, ids=list(CUSTOM_OPENAI_PROVIDER_KEYS))
def test_multi_provider_custom_openai_missing_api_key_fails_without_assistant_message(monkeypatch, provider_key):
    test_run_id = _test_run_id(f"a7-{provider_key}-missing-key")
    case = _PROVIDER_CASES[provider_key]
    agent_id = f"{case['agent_id']}-{test_run_id}"
    monkeypatch.setenv(case["api_base_env"], f"https://{provider_key}.example.test/v1")
    monkeypatch.setenv(case["model_env"], f"{provider_key}-model")
    monkeypatch.delenv(case["credential_env"], raising=False)
    _insert_agent(agent_id, provider=provider_key, configured=True, execution_enabled=True)
    _assert_provider_agent_shape(agent_id, provider_key)
    conversation, message = _conversation_and_message(agent_id, test_run_id)

    health = AdapterRegistry().health_for_agent(_provider_agent_profile(agent_id, provider_key))
    assert health.configured is False
    assert health.status == "missing_credentials"
    assert health.error_code == "missing_credentials"

    run = create_run_from_body(
        _run_payload(
            provider_key,
            agent_id,
            message,
            "This must fail before a provider call because the provider key is missing.",
        ),
        test_run_id=test_run_id,
    )

    events = list_run_events(str(run["id"]), test_run_id=test_run_id)
    messages = list_messages(str(conversation["id"]), test_run_id=test_run_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "missing_credentials"
    assert [event["type"] for event in events] == ["run_created", "run_started", "adapter_error", "run_failed"]
    assert len(messages) == 1
    _assert_no_task_plan_step_records(str(conversation["id"]), test_run_id)
    _assert_no_artifact_diff_deploy_records(test_run_id)
    _assert_env_secrets_not_leaked({"run": run, "events": events, "messages": messages}, [case["credential_env"]])


def test_custom_openai_missing_api_key_fails_without_assistant_message(monkeypatch):
    test_run_id = _test_run_id("a7-custom-missing-key")
    agent_id = f"agent-{test_run_id}"
    monkeypatch.setenv("AGENTHUB_OPENAI_API_BASE", "https://api.example.test/v1")
    monkeypatch.setenv("AGENTHUB_OPENAI_MODEL", "example-model")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _insert_agent(agent_id, provider="openai")
    conversation, message = _conversation_and_message(agent_id, test_run_id)

    run = create_run_from_body(
        {
            "source_type": "message",
            "source_message_id": message["id"],
            "target_agent_id": agent_id,
            "run_mode": "direct_response",
            "instruction": "This must fail before a provider call because the key is missing.",
            "context_bundle": {},
            "workspace_ref": None,
            "allowed_tools": [],
            "expected_artifacts": [],
        },
        test_run_id=test_run_id,
    )

    events = list_run_events(str(run["id"]), test_run_id=test_run_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "missing_credentials"
    assert [event["type"] for event in events] == ["run_created", "run_started", "adapter_error", "run_failed"]
    assert len(list_messages(str(conversation["id"]), test_run_id=test_run_id)) == 1


def test_codex_executable_missing_fails_without_assistant_message(monkeypatch):
    test_run_id = _test_run_id("a7-codex-missing-exe")
    agent_id = f"agent-{test_run_id}"
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", "Z:/definitely/missing/codex.exe")
    _insert_agent(agent_id, provider="codex")
    conversation, message = _conversation_and_message(agent_id, test_run_id)

    health = AdapterRegistry().health_for_agent(_provider_agent_profile(agent_id, "codex"))
    assert health.configured is False
    assert health.error_code == "adapter_executable_not_found"

    run = create_run_from_body(
        {
            "source_type": "message",
            "source_message_id": message["id"],
            "target_agent_id": agent_id,
            "run_mode": "direct_response",
            "instruction": "This must fail before Codex starts.",
            "context_bundle": {},
            "workspace_ref": None,
            "allowed_tools": [],
            "expected_artifacts": [],
        },
        test_run_id=test_run_id,
    )

    events = list_run_events(str(run["id"]), test_run_id=test_run_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "adapter_executable_not_found"
    assert "run_succeeded" not in [event["type"] for event in events]
    assert len(list_messages(str(conversation["id"]), test_run_id=test_run_id)) == 1


def test_claude_code_executable_missing_fails_without_assistant_message(monkeypatch):
    test_run_id = _test_run_id("a7-claude-missing-exe")
    agent_id = f"agent-{test_run_id}"
    monkeypatch.setenv("AGENTHUB_CLAUDE_CODE_EXECUTABLE", "Z:/definitely/missing/claude.exe")
    _insert_agent(agent_id, provider="anthropic")
    conversation, message = _conversation_and_message(agent_id, test_run_id)

    health = AdapterRegistry().health_for_agent(_provider_agent_profile(agent_id, "anthropic"))
    assert health.configured is False
    assert health.error_code == "adapter_executable_not_found"

    run = create_run_from_body(
        {
            "source_type": "message",
            "source_message_id": message["id"],
            "target_agent_id": agent_id,
            "run_mode": "direct_response",
            "instruction": "This must fail before Claude Code starts.",
            "context_bundle": {},
            "workspace_ref": None,
            "allowed_tools": [],
            "expected_artifacts": [],
        },
        test_run_id=test_run_id,
    )

    events = list_run_events(str(run["id"]), test_run_id=test_run_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "adapter_executable_not_found"
    assert "run_succeeded" not in [event["type"] for event in events]
    assert len(list_messages(str(conversation["id"]), test_run_id=test_run_id)) == 1


def test_codex_real_cli_executable_preflight_and_read_only_template():
    executable = _real_cli_path("AGENTHUB_CODEX_EXECUTABLE", "Codex")
    test_run_id = _test_run_id("a7-codex-real-preflight")
    agent_id = f"agent-{test_run_id}"
    _insert_agent(agent_id, provider="codex")

    health = AdapterRegistry().health_for_agent(_provider_agent_profile(agent_id, "codex"))
    command = build_codex_direct_response_command(
        executable_path=executable,
        workspace_dir="D:/AgentHub",
        prompt="hello",
    )

    assert health.error_code != "adapter_executable_not_found"
    assert command[:4] == [executable, "-a", "never", "exec"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "danger-full-access" not in command
    assert "workspace-write" not in command


def test_claude_code_real_cli_executable_preflight_and_tools_disabled_template():
    executable = _real_cli_path("AGENTHUB_CLAUDE_CODE_EXECUTABLE", "Claude Code")
    test_run_id = _test_run_id("a7-claude-real-preflight")
    agent_id = f"agent-{test_run_id}"
    _insert_agent(agent_id, provider="anthropic")

    health = AdapterRegistry().health_for_agent(_provider_agent_profile(agent_id, "anthropic"))
    command = build_claude_direct_response_command(executable_path=executable, prompt="hello")

    assert health.error_code != "adapter_executable_not_found"
    assert "--tools=" in command
    assert "--strict-mcp-config" in command
    assert "--dangerously-skip-permissions" not in command
    assert "Edit" not in command
    assert "Write" not in command
    assert "Bash" not in command


def test_codex_401_jsonl_sample_fails_without_assistant_message():
    result = CliProcessResult(
        argv=["codex"],
        cwd="D:/AgentHub",
        exit_code=1,
        stdout_lines=[
            '{"type":"thread.started","thread_id":"t1"}',
            '{"type":"turn.started"}',
            '{"type":"error","message":"401 Unauthorized: Missing bearer"}',
            '{"type":"turn.failed","error":{"message":"stream disconnected before completion"}}',
        ],
        stderr_lines=[],
        raw_lines=[
            CliRawLine(stream="stdout", line='{"type":"thread.started","thread_id":"t1"}'),
            CliRawLine(stream="stdout", line='{"type":"turn.started"}'),
            CliRawLine(stream="stdout", line='{"type":"error","message":"401 Unauthorized: Missing bearer"}'),
            CliRawLine(stream="stdout", line='{"type":"turn.failed","error":{"message":"stream disconnected before completion"}}'),
        ],
        timed_out=False,
        duration_seconds=1.0,
    )

    events = _events_from_codex_result(result)

    assert any(event.type == "backend_session_started" for event in events)
    assert any(event.payload.get("error_code") == "backend_auth_failed" for event in events)
    assert not any(event.type == "assistant_message_completed" for event in events)


def test_claude_system_init_sample_maps_backend_session_started():
    event = parse_claude_stream_json_line(
        '{"type":"system","subtype":"init","cwd":"D:/AgentHub","session_id":"s1",'
        '"model":"claude","tools":[],"mcp_servers":[],"apiKeySource":"none",'
        '"claude_code_version":"2.1.170"}'
    )

    assert event.type == "backend_session_started"
    assert event.payload["tools"] == []
    assert event.payload["mcp_servers"] == []


def test_claude_api_retry_timeout_fails_without_assistant_message(monkeypatch):
    monkeypatch.setenv(CLAUDE_CODE_REAL_CLI_ENV, "1")
    config = validate_provider_config(
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
    adapter = ClaudeCodeCliAdapter(config=config, target_agent_id="agent-claude")

    monkeypatch.setattr("services.api.app.agents.adapters.claude_code_cli.resolve_executable", lambda _: "claude")
    monkeypatch.setattr(
        "services.api.app.agents.adapters.claude_code_cli.run_cli_process",
        lambda *args, **kwargs: CliProcessResult(
            argv=["claude"],
            cwd="D:/AgentHub",
            exit_code=None,
            stdout_lines=['{"type":"system","subtype":"api_retry","message":"retrying"}'],
            stderr_lines=[],
            raw_lines=[
                CliRawLine(stream="stdout", line='{"type":"system","subtype":"api_retry","message":"retrying"}')
            ],
            timed_out=True,
            duration_seconds=1.0,
        ),
    )

    events = adapter.invoke(
        type(
            "Request",
            (),
            {
                "run_mode": "direct_response",
                "instruction": "hello",
                "workspace_ref": None,
            },
        )()
    )

    assert any(event.type == "backend_retry" for event in events)
    assert any(event.type == "run_timed_out" for event in events)
    assert not any(event.type == "assistant_message_completed" for event in events)


def test_codex_real_cli_direct_response_success_auth_failure_or_timeout(monkeypatch):
    _real_cli_path("AGENTHUB_CODEX_EXECUTABLE", "Codex")
    if not os.getenv("AGENTHUB_CODEX_TIMEOUT_SECONDS"):
        monkeypatch.setenv("AGENTHUB_CODEX_TIMEOUT_SECONDS", "15")
    test_run_id = _test_run_id("a7-codex-real-runtime")
    agent_id = f"agent-{test_run_id}"
    _insert_agent(agent_id, provider="codex")
    health = AdapterRegistry().health_for_agent(_provider_agent_profile(agent_id, "codex"))
    if not health.configured and health.error_code not in {
        "backend_auth_failed",
        "adapter_auth_missing",
        "adapter_timeout",
    }:
        pytest.skip(f"Codex CLI did not reach success/auth runtime state: {health.error_code}")

    conversation, message = _conversation_and_message(agent_id, test_run_id)
    run = create_run_from_body(
        _run_payload(
            "codex",
            agent_id,
            message,
            "Reply with exactly this short sentence: AgentHub Codex direct response works.",
        ),
        test_run_id=test_run_id,
    )

    events = list_run_events(str(run["id"]), test_run_id=test_run_id)
    event_types = [event["type"] for event in events]
    messages = list_messages(str(conversation["id"]), test_run_id=test_run_id)
    assistant_messages = [item for item in messages if item["sender_type"] == "assistant"]

    assert event_types[:2] == ["run_created", "run_started"]
    _assert_no_task_plan_step_records(str(conversation["id"]), test_run_id)
    _assert_no_artifact_diff_deploy_records(test_run_id)

    if run["status"] == "succeeded":
        assert run["error_code"] is None
        assert "assistant_message_completed" in event_types
        assert "run_succeeded" in event_types
        assert event_types.index("assistant_message_completed") < event_types.index("run_succeeded")
        assert len(assistant_messages) == 1
        assert assistant_messages[0]["created_by_run_id"] == run["id"]
        assert assistant_messages[0]["content"]["run_id"] == run["id"]
        assert assistant_messages[0]["content"]["text"].strip()
        return

    if run["error_code"] not in {"backend_auth_failed", "adapter_auth_missing", "run_timed_out"}:
        pytest.skip(f"Codex CLI produced neither success, auth failure, nor timeout: {run['error_code']}")
    assert run["status"] == "failed"
    assert "run_failed" in event_types
    assert "run_succeeded" not in event_types
    assert "assistant_message_completed" not in event_types
    assert len(assistant_messages) == 0
    if run["error_code"] == "run_timed_out":
        assert "run_timed_out" in event_types
    assert any(event_type in event_types for event_type in ("backend_session_started", "raw_backend_event"))
    assert any(event_type in event_types for event_type in ("stdout_line", "stderr_line"))
    _assert_no_assistant_message(str(conversation["id"]), test_run_id)


def test_claude_code_real_cli_direct_response_success_or_retry_timeout(monkeypatch):
    _real_cli_path("AGENTHUB_CLAUDE_CODE_EXECUTABLE", "Claude Code")
    if not os.getenv("AGENTHUB_ANTHROPIC_TIMEOUT_SECONDS"):
        monkeypatch.setenv("AGENTHUB_ANTHROPIC_TIMEOUT_SECONDS", "8")
    test_run_id = _test_run_id("a7-claude-real-runtime")
    agent_id = f"agent-{test_run_id}"
    _insert_agent(agent_id, provider="anthropic")
    health = AdapterRegistry().health_for_agent(_provider_agent_profile(agent_id, "anthropic"))
    if not health.configured and health.error_code not in {"adapter_auth_unusable", "adapter_timeout"}:
        pytest.skip(f"Claude Code did not reach success/retry-timeout runtime state: {health.error_code}")

    conversation, message = _conversation_and_message(agent_id, test_run_id)
    run = create_run_from_body(
        _run_payload(
            "anthropic",
            agent_id,
            message,
            "Reply with exactly this short sentence: AgentHub Claude Code direct response works.",
        ),
        test_run_id=test_run_id,
    )

    events = list_run_events(str(run["id"]), test_run_id=test_run_id)
    event_types = [event["type"] for event in events]
    messages = list_messages(str(conversation["id"]), test_run_id=test_run_id)
    assistant_messages = [item for item in messages if item["sender_type"] == "assistant"]

    assert event_types[:2] == ["run_created", "run_started"]
    _assert_no_task_plan_step_records(str(conversation["id"]), test_run_id)
    _assert_no_artifact_diff_deploy_records(test_run_id)

    if run["status"] == "succeeded":
        assert run["error_code"] is None
        assert "backend_session_started" in event_types
        assert "assistant_message_completed" in event_types
        assert "run_succeeded" in event_types
        assert event_types.index("assistant_message_completed") < event_types.index("run_succeeded")
        assert len(assistant_messages) == 1
        assert assistant_messages[0]["created_by_run_id"] == run["id"]
        assert assistant_messages[0]["content"]["run_id"] == run["id"]
        assert assistant_messages[0]["content"]["text"].strip()
        return

    if run["error_code"] not in {"run_timed_out", "adapter_auth_unusable"}:
        pytest.skip(f"Claude Code produced neither success nor retry timeout: {run['error_code']}")
    assert run["status"] == "failed"
    if os.getenv(CLAUDE_CODE_REAL_CLI_ENV) == "1":
        assert "backend_retry" in event_types
        assert "adapter_process_started" in event_types
    else:
        assert "backend_retry" not in event_types
        assert "adapter_process_started" not in event_types
    assert any(event_type in event_types for event_type in ("run_timed_out", "run_failed"))
    assert "run_succeeded" not in event_types
    assert "assistant_message_completed" not in event_types
    assert len(assistant_messages) == 0
    _assert_no_assistant_message(str(conversation["id"]), test_run_id)


@pytest.mark.parametrize("provider_key", CUSTOM_OPENAI_PROVIDER_KEYS, ids=list(CUSTOM_OPENAI_PROVIDER_KEYS))
def test_multi_provider_custom_openai_real_success_writes_assistant_message_when_configured(provider_key):
    case = _PROVIDER_CASES[provider_key]
    env_names = (case["api_base_env"], case["model_env"], case["credential_env"])
    if not _real_provider_env_complete(provider_key):
        pytest.skip(
            "requires AGENTHUB_RUN_REAL_PROVIDER_TESTS=1 and complete provider env for "
            f"{provider_key}: {', '.join(env_names)}"
        )

    successful_attempt = None
    last_failure = None
    for attempt in range(2):
        test_run_id = _test_run_id(f"a7-{provider_key}-real-success")
        agent_id = f"{case['agent_id']}-{test_run_id}"
        _insert_agent(agent_id, provider=provider_key, configured=True, execution_enabled=True)
        _assert_provider_agent_shape(agent_id, provider_key)

        health = AdapterRegistry().health_for_agent(_provider_agent_profile(agent_id, provider_key))
        assert health.configured is True
        assert health.status == "ready"
        assert health.error_code is None
        assert "direct_response" in health.capabilities

        conversation, message = _conversation_and_message(agent_id, test_run_id)
        run = create_run_from_body(
            _run_payload(
                provider_key,
                agent_id,
                message,
                "Answer in one short sentence: AgentHub A7 multi-provider direct response is working.",
            ),
            test_run_id=test_run_id,
        )

        events = list_run_events(str(run["id"]), test_run_id=test_run_id)
        event_types = [event["type"] for event in events]
        messages = list_messages(str(conversation["id"]), test_run_id=test_run_id)
        assistant_messages = [item for item in messages if item["sender_type"] == "assistant"]
        _assert_no_task_plan_step_records(str(conversation["id"]), test_run_id)
        _assert_no_artifact_diff_deploy_records(test_run_id)
        _assert_env_secrets_not_leaked(
            {"run": run, "events": events, "messages": messages, "health": health.__dict__},
            (case["credential_env"],),
        )

        if run["status"] == "succeeded":
            successful_attempt = (run, events, event_types, assistant_messages)
            break

        assert "run_succeeded" not in event_types
        assert "assistant_message_completed" not in event_types
        assert len(assistant_messages) == 0
        last_failure = run
        if attempt == 1 or run["error_code"] not in {"backend_network_failed", "adapter_timeout"}:
            break

    if successful_attempt is None:
        pytest.fail(
            "custom_openai real provider did not produce a successful final assistant output: "
            f"{last_failure['error_code'] if last_failure else 'no_run'}"
        )

    run, events, event_types, assistant_messages = successful_attempt

    assert run["status"] == "succeeded"
    assert run["error_code"] is None
    assert event_types[:2] == ["run_created", "run_started"]
    assert "assistant_message_completed" in event_types
    assert "run_succeeded" in event_types
    assert event_types.index("assistant_message_completed") < event_types.index("run_succeeded")
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["created_by_run_id"] == run["id"]
    assert assistant_messages[0]["content"]["run_id"] == run["id"]
    assert assistant_messages[0]["content"]["text"].strip()
    assert run.get("assistant_message", {}).get("created_by_run_id") == run["id"]
