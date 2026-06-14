import json
import socket
import urllib.error
import uuid
from pathlib import Path

import pytest

from services.api.app.orchestration.planner_trace import list_planner_traces
from services.api.app.orchestration.turn_backends.base import TurnRequest, TurnRouterBackendError
from services.api.app.orchestration.turn_backends.openai_compatible import OpenAICompatibleTurnRouterBackend


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _request(test_run_id="contract-openai-router"):
    return TurnRequest(
        message_id="msg_openai_router",
        conversation_id="conv_openai_router",
        message_text="Create a plan from structured router output.",
        sender_type="user",
        sender_id="user",
        conversation_mode="group_agent",
        content={"text": "Create a plan from structured router output."},
        references=[],
        mentions=[],
        available_agents=[
            {
                "id": "agent-code",
                "name": "Code Agent",
                "provider": "openai",
                "capability_tags": ["code"],
                "enabled": True,
                "configured": False,
                "execution_enabled": False,
                "health_status": "profile_only",
            }
        ],
        available_artifact_types=["document", "source_file"],
        private_agent_id=None,
        auto_orchestrate=True,
        pinned_context=[],
        recent_messages=[],
        test_run_id=test_run_id,
    )


def _decision(**overrides):
    payload = {
        "decision_type": "plan_task",
        "target_type": "orchestrator",
        "target_source": "auto_orchestrate",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": "Create a structured implementation plan",
        "steps": [
            {
                "kind": "implementation",
                "objective": "Implement the requested change",
                "required_capabilities": ["code"],
                "depends_on": [],
                "expected_output": {"type": "plan"},
            }
        ],
        "reason": "Provider returned a structured plan",
        "confidence": "high",
        "clarification_question": None,
    }
    payload.update(overrides)
    return payload


def _backend(**overrides):
    config = {
        "base_url": "https://router.example.test/v1",
        "api_key": "test-key",
        "model": "router-model",
        "timeout_seconds": 3,
    }
    config.update(overrides)
    return OpenAICompatibleTurnRouterBackend(**config)


def _isolated_db(monkeypatch):
    path = Path("var") / f"turn_router_contract_{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(path))
    return path


def test_openai_turn_router_missing_config_maps_not_configured(monkeypatch):
    _isolated_db(monkeypatch)
    backend = OpenAICompatibleTurnRouterBackend(base_url="", api_key="", model="")

    with pytest.raises(TurnRouterBackendError) as exc_info:
        backend.decide(_request())

    assert exc_info.value.code == "turn_router_not_configured"
    traces = list_planner_traces(test_run_id="contract-openai-router")
    assert traces[-1]["error_code"] == "turn_router_not_configured"


def test_openai_turn_router_valid_plan_task_uses_json_schema(monkeypatch):
    _isolated_db(monkeypatch)
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"choices": [{"message": {"content": json.dumps(_decision())}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    decision = _backend().decide(_request())

    assert decision.decision_type == "plan_task"
    assert captured["url"] == "https://router.example.test/v1/chat/completions"
    assert captured["timeout"] == 3
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert captured["body"]["response_format"]["json_schema"]["strict"] is True
    traces = list_planner_traces(test_run_id="contract-openai-router")
    assert traces[-1]["decision_type"] == "plan_task"
    assert traces[-1]["raw_output_hash"]


def test_openai_turn_router_can_use_json_object_mode(monkeypatch):
    _isolated_db(monkeypatch)
    captured = {}

    def fake_urlopen(request, timeout):
        del timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"choices": [{"message": {"content": json.dumps(_decision())}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    _backend(response_format="json_object").decide(_request())

    assert captured["body"]["response_format"] == {"type": "json_object"}


def test_openai_turn_router_invalid_json_maps_invalid_output(monkeypatch):
    _isolated_db(monkeypatch)

    def fake_urlopen(request, timeout):
        del request, timeout
        return _FakeResponse({"choices": [{"message": {"content": "not json"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(TurnRouterBackendError) as exc_info:
        _backend().decide(_request())

    assert exc_info.value.code == "turn_router_invalid_output"
    traces = list_planner_traces(test_run_id="contract-openai-router")
    assert traces[-1]["error_code"] == "turn_router_invalid_output"


def test_openai_turn_router_schema_error_maps_invalid_output(monkeypatch):
    _isolated_db(monkeypatch)

    def fake_urlopen(request, timeout):
        del request, timeout
        return _FakeResponse({"choices": [{"message": {"content": json.dumps(_decision(steps=[]))}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(TurnRouterBackendError) as exc_info:
        _backend().decide(_request())

    assert exc_info.value.code == "turn_router_invalid_output"


def test_openai_turn_router_http_error_maps_provider_failed(monkeypatch):
    _isolated_db(monkeypatch)

    def fake_urlopen(request, timeout):
        del timeout
        raise urllib.error.HTTPError(request.full_url, 500, "boom", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(TurnRouterBackendError) as exc_info:
        _backend().decide(_request())

    assert exc_info.value.code == "turn_router_provider_failed"


def test_openai_turn_router_timeout_maps_provider_timeout(monkeypatch):
    _isolated_db(monkeypatch)

    def fake_urlopen(request, timeout):
        del request, timeout
        raise socket.timeout("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(TurnRouterBackendError) as exc_info:
        _backend().decide(_request())

    assert exc_info.value.code == "turn_router_provider_timeout"
