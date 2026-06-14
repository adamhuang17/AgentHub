import pytest

from services.api.app.orchestration.turn_backends.base import TurnRouterBackendError
from services.api.app.orchestration.turn_backends.disabled import DisabledTurnRouterBackend
from services.api.app.orchestration.turn_backends.test_backend import TestTurnRouterBackend
from services.api.app.orchestration.turn_router_gateway import TurnRouterGateway


def _message(text="The text must not be classified locally."):
    return {
        "id": "message-contract",
        "conversation_id": "conversation-contract",
        "content": {"text": text},
        "mentions": [],
        "references": [],
    }


def _no_action_decision():
    return {
        "decision_type": "no_action",
        "target_type": "none",
        "target_source": "none",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": None,
        "steps": [],
        "reason": "test fixture says no action",
        "confidence": "high",
        "clarification_question": None,
    }


def _enable_test_backend(monkeypatch):
    monkeypatch.setenv("AGENTHUB_ENV", "test")
    monkeypatch.setenv("AGENTHUB_ENABLE_TEST_TURN_ROUTER_BACKEND", "1")
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BACKEND", "test")


def test_turn_router_backend_disabled_returns_not_configured():
    gateway = TurnRouterGateway(DisabledTurnRouterBackend())

    with pytest.raises(TurnRouterBackendError) as exc_info:
        gateway.decide_for_message(
            _message(),
            conversation_mode="group",
            private_agent_id=None,
            auto_orchestrate=True,
        )

    assert exc_info.value.code == "turn_router_not_configured"


def test_test_turn_router_backend_requires_test_env(monkeypatch):
    monkeypatch.delenv("AGENTHUB_ENV", raising=False)
    monkeypatch.setenv("AGENTHUB_ENABLE_TEST_TURN_ROUTER_BACKEND", "1")
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BACKEND", "test")

    with pytest.raises(TurnRouterBackendError) as exc_info:
        TestTurnRouterBackend(_no_action_decision())

    assert exc_info.value.code == "turn_router_not_configured"


def test_test_turn_router_backend_uses_injected_decision_not_message_text(monkeypatch):
    _enable_test_backend(monkeypatch)
    gateway = TurnRouterGateway(TestTurnRouterBackend(_no_action_decision()))

    decision = gateway.decide_for_message(
        _message("Implement and review the service, but injected decision wins."),
        conversation_mode="group",
        private_agent_id=None,
        auto_orchestrate=True,
    )

    assert decision.decision_type == "no_action"
    assert decision.steps == []


def test_test_turn_router_backend_requires_injected_decision(monkeypatch):
    _enable_test_backend(monkeypatch)

    with pytest.raises(TurnRouterBackendError) as exc_info:
        TestTurnRouterBackend(None).decide(None)  # type: ignore[arg-type]

    assert exc_info.value.code == "turn_router_not_configured"


def test_gateway_builds_structured_turn_request_without_classifying_text():
    captured = {}

    class CaptureBackend:
        def decide(self, request):
            captured["request"] = request
            return request

    gateway = TurnRouterGateway(CaptureBackend())
    request = gateway.decide_for_message(
        {
            "id": "message-structured",
            "conversation_id": "conversation-structured",
            "sender_type": "user",
            "sender_id": "user",
            "content": {"text": "This text must not be locally classified."},
            "mentions": [{"agent_id": "agent-codex-profile"}],
            "references": [{"type": "artifact", "artifact_id": "art-1"}],
        },
        conversation_mode="group_agent",
        private_agent_id=None,
        auto_orchestrate=True,
    )

    assert request.message_text == "This text must not be locally classified."
    assert request.sender_type == "user"
    assert request.mentions == [{"agent_id": "agent-codex-profile"}]
    assert request.references == [{"type": "artifact", "artifact_id": "art-1"}]
    assert request.available_agents
    assert {"id", "name", "provider", "capability_tags", "enabled", "configured", "health_status"}.issubset(
        request.available_agents[0]
    )
    assert "document" in request.available_artifact_types
