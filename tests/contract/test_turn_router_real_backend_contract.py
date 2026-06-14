import inspect

import pytest

import services.api.app.shared.settings as settings_module
from services.api.app.orchestration.turn_backends.base import TurnRouterBackendError
from services.api.app.orchestration.turn_backends.disabled import DisabledTurnRouterBackend
from services.api.app.orchestration.turn_backends.openai_compatible import (
    OpenAICompatibleTurnRouterBackend,
    _coerce_provider_decision,
    _parse_turn_decision_json,
)
from services.api.app.orchestration.turn_backends.test_backend import TestTurnRouterBackend
from services.api.app.orchestration.turn_router_gateway import gateway_from_environment, turn_router_backend_configured


def _decision():
    return {
        "decision_type": "no_action",
        "target_type": "none",
        "target_source": "none",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": None,
        "steps": [],
        "reason": "contract fixture",
        "confidence": "high",
        "clarification_question": None,
    }


def test_gateway_uses_openai_compatible_backend_when_configured(monkeypatch):
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BACKEND", "openai_compatible")
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BASE_URL", "https://router.example.test/v1")
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_API_KEY", "test-key")
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_MODEL", "router-model")

    gateway = gateway_from_environment()

    assert isinstance(gateway.backend, OpenAICompatibleTurnRouterBackend)
    assert turn_router_backend_configured() is True


def test_gateway_does_not_treat_unknown_backend_as_configured(monkeypatch):
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BACKEND", "unknown")

    gateway = gateway_from_environment()

    assert isinstance(gateway.backend, DisabledTurnRouterBackend)
    assert turn_router_backend_configured() is False


def test_injected_turn_decision_requires_explicit_test_backend(monkeypatch):
    monkeypatch.setenv("AGENTHUB_ENV", "test")
    monkeypatch.setenv("AGENTHUB_ENABLE_TEST_TURN_ROUTER_BACKEND", "1")
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BACKEND", "disabled")

    gateway = gateway_from_environment(_decision())

    assert isinstance(gateway.backend, DisabledTurnRouterBackend)


def test_test_backend_is_enabled_only_by_explicit_env(monkeypatch):
    monkeypatch.setenv("AGENTHUB_ENV", "test")
    monkeypatch.setenv("AGENTHUB_ENABLE_TEST_TURN_ROUTER_BACKEND", "1")
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BACKEND", "test")

    gateway = gateway_from_environment(_decision())

    assert isinstance(gateway.backend, TestTurnRouterBackend)


def test_test_backend_refuses_non_test_environment(monkeypatch):
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BACKEND", "test")
    monkeypatch.setenv("AGENTHUB_ENABLE_TEST_TURN_ROUTER_BACKEND", "1")
    monkeypatch.delenv("AGENTHUB_ENV", raising=False)

    with pytest.raises(TurnRouterBackendError) as exc_info:
        gateway_from_environment(_decision())

    assert exc_info.value.code == "turn_router_not_configured"


def test_turn_router_env_names_are_documented_in_code():
    expected = {
        "AGENTHUB_TURN_ROUTER_BASE_URL",
        "AGENTHUB_TURN_ROUTER_API_KEY",
        "AGENTHUB_TURN_ROUTER_MODEL",
        "AGENTHUB_TURN_ROUTER_TIMEOUT_SECONDS",
    }
    source = inspect.getsource(OpenAICompatibleTurnRouterBackend) + inspect.getsource(settings_module)
    for env_name in expected:
        assert env_name in source


def test_openai_compatible_router_extracts_json_from_fenced_content():
    parsed = _parse_turn_decision_json(
        """
        Here is the decision:
        ```json
        {"decision_type":"no_action","target_type":"none","target_source":"none","target_agent_id":null,"target_agent_ids":[],"goal":null,"steps":[],"reason":"ok","confidence":"high","clarification_question":null}
        ```
        """
    )

    assert parsed["decision_type"] == "no_action"


def test_openai_compatible_router_coerces_common_step_aliases():
    parsed = _coerce_provider_decision(
        {
            "decision_type": "plan",
            "steps": [
                {"kind": "planning", "objective": "Analyze", "required_capabilities": [], "depends_on": [], "expected_output": {}},
                {"kind": "code", "objective": "Build", "required_capabilities": [], "depends_on": ["step-1"], "expected_output": {}},
                {"kind": "qa", "objective": "Review", "required_capabilities": [], "depends_on": ["step-2"], "expected_output": {}},
            ],
        }
    )

    assert parsed["decision_type"] == "plan_task"
    assert [step["kind"] for step in parsed["steps"]] == ["analysis", "implementation", "review"]
    assert parsed["target_type"] == "orchestrator"


def test_openai_compatible_router_treats_direct_response_with_steps_as_plan():
    parsed = _coerce_provider_decision(
        {
            "decision_type": "direct_response",
            "target_type": "orchestrator",
            "target_source": "auto_orchestrate",
            "goal": "Break down the demo rescue work.",
            "steps": [
                {"kind": "analysis", "objective": "Analyze the flow."},
                {"kind": "implementation", "objective": "Fix the flow."},
                {"kind": "review", "objective": "Review the result."},
            ],
        }
    )

    assert parsed["decision_type"] == "plan_task"
    assert parsed["goal"] == "Break down the demo rescue work."
    assert [step["kind"] for step in parsed["steps"]] == ["analysis", "implementation", "review"]


def test_openai_compatible_router_strips_plan_fields_from_plain_direct_response():
    parsed = _coerce_provider_decision(
        {
            "decision_type": "answer",
            "target_type": "orchestrator",
            "target_source": "auto_orchestrate",
            "goal": "Should not be present for direct response.",
            "steps": [],
            "clarification_question": "Also invalid here.",
        }
    )

    assert parsed["decision_type"] == "direct_response"
    assert parsed["goal"] is None
    assert parsed["steps"] == []
    assert parsed["clarification_question"] is None
