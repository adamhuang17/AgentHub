from http import HTTPStatus

import services.api.app.agent_runs.service as agent_run_service
from services.api.app.agent_runs.schema import AgentRunEventDraft
from services.api.app.agents.adapter_health import adapter_health
from services.api.app.conversations.repository import create_conversation, list_conversation_events, list_messages
from services.api.app.conversations.routes import handle_post


def _router_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTHUB_PROFILE", "test")
    monkeypatch.setenv("AGENTHUB_ENV", "test")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "router-defaults.sqlite3"))
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BACKEND", "test")
    monkeypatch.setenv("AGENTHUB_ENABLE_TEST_TURN_ROUTER_BACKEND", "1")
    monkeypatch.setenv("AGENTHUB_MODEL_PROVIDER", "custom_openai")
    monkeypatch.setenv("AGENTHUB_CODEX_EXECUTABLE", str(tmp_path / "missing-codex.exe"))
    monkeypatch.setenv("AGENTHUB_CLAUDE_CODE_EXECUTABLE", str(tmp_path / "missing-claude.exe"))
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "")


def _direct_response_without_target_type():
    return {
        "decision_type": "direct_response",
        "target_source": "auto_orchestrate",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": None,
        "steps": [],
        "reason": "Simple group message should stay with the orchestrator.",
        "confidence": "high",
        "clarification_question": None,
    }


def _patch_successful_model_adapter(monkeypatch, text="Default model response."):
    class FakeAdapter:
        adapter_id = "fixture-model"

        def invoke(self, request):
            del request
            return [
                AgentRunEventDraft(type="assistant_message_completed", payload={"content_text": text}),
                AgentRunEventDraft(type="run_succeeded", payload={"status": "succeeded"}),
            ]

        def cancel(self, run_id):
            return {"run_id": run_id, "cancel_requested": False}

    class FakeRegistry:
        def adapter_for_agent(self, agent):
            del agent
            return FakeAdapter()

        def health_for_agent(self, agent):
            return adapter_health(
                provider=str(agent["provider"]),
                adapter_kind="custom_openai",
                configured=True,
                status="ready",
                error_code=None,
                recovery_hint=None,
                capabilities=["direct_response"],
            )

    monkeypatch.setattr(agent_run_service, "AdapterRegistry", FakeRegistry)


def test_group_direct_response_missing_target_type_returns_explicit_error_without_default_agent(monkeypatch, tmp_path):
    _router_env(monkeypatch, tmp_path)
    test_run_id = "router-defaults"
    conversation = create_conversation(
        title="Router defaults",
        mode="group",
        agent_ids=[],
        test_run_id=test_run_id,
    )

    status, payload = handle_post(
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "What is the project status?"},
            "turn_decision": _direct_response_without_target_type(),
        },
        test_run_id,
    )

    assert status == HTTPStatus.CREATED
    assert payload["dispatch_path"] == "failed"
    assert payload["error_code"] == "direct_response_target_unavailable"
    assert payload["message"]["id"]
    assert payload["error_card"]["error_code"] == "direct_response_target_unavailable"
    assert list_messages(conversation["id"], test_run_id=test_run_id)[0]["content"]["text"] == "What is the project status?"
    events = list_conversation_events(conversation["id"], test_run_id=test_run_id)
    decision = next(event for event in events if event["type"] == "planner.decision_created")
    assert decision["payload_json"]["target_type"] == "orchestrator"
    failure = next(event for event in events if event["type"] == "planner.decision_failed")
    assert failure["payload_json"]["error_code"] == "direct_response_target_unavailable"


def test_group_orchestrator_direct_response_uses_configured_default_model_agent(monkeypatch, tmp_path):
    _router_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "https://model.example/v1")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "fixture-model")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "fixture-key")
    _patch_successful_model_adapter(monkeypatch, text="Routed through the default model agent.")
    test_run_id = "router-default-model"
    conversation = create_conversation(
        title="Router default model",
        mode="group",
        agent_ids=[],
        test_run_id=test_run_id,
    )

    status, payload = handle_post(
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "Give a short answer."},
            "turn_decision": _direct_response_without_target_type(),
        },
        test_run_id,
    )

    assert status == HTTPStatus.CREATED
    assert payload["run_id"]
    assert payload["agent_run"]["target_agent_id"] == "agent-demo-model"
    assert payload["agent_run"]["status"] == "succeeded"
    assert payload["assistant_message"]["sender_id"] == "agent-demo-model"
    assert payload["assistant_message"]["content"]["text"] == "Routed through the default model agent."


def test_invalid_router_schema_returns_retryable_error(monkeypatch, tmp_path):
    _router_env(monkeypatch, tmp_path)
    test_run_id = "router-invalid"
    conversation = create_conversation(
        title="Router invalid",
        mode="group",
        agent_ids=[],
        test_run_id=test_run_id,
    )

    status, payload = handle_post(
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "Please route this."},
            "turn_decision": {
                **_direct_response_without_target_type(),
                "target_agent_ids": "not-a-list",
            },
        },
        test_run_id,
    )

    assert status == HTTPStatus.CREATED
    assert payload["dispatch_path"] == "failed"
    assert payload["error_code"] == "turn_router_invalid_output"
    assert payload["error_message"] == "Router output invalid."
    assert payload["message"]["content"]["text"] == "Please route this."
    assert payload["error_card"]["error_code"] == "turn_router_invalid_output"
    assert "Retry" in payload["recovery_hint"]
    events = list_conversation_events(conversation["id"], test_run_id=test_run_id)
    assert any(event["type"] == "router.output_invalid" for event in events)
    failure = next(event for event in events if event["type"] == "planner.decision_failed")
    assert failure["payload_json"]["error_code"] == "turn_router_invalid_output"


def test_private_direct_response_missing_target_type_fills_agent_target(monkeypatch, tmp_path):
    _router_env(monkeypatch, tmp_path)
    test_run_id = "router-private-default"
    conversation = create_conversation(
        title="Router private defaults",
        mode="private_agent",
        agent_ids=["agent-demo-model"],
        test_run_id=test_run_id,
    )

    status, payload = handle_post(
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "Answer in this private chat."},
            "turn_decision": _direct_response_without_target_type(),
        },
        test_run_id,
    )

    assert status == HTTPStatus.CREATED
    assert payload["dispatch_path"] == "blocked"
    assert payload["agent_run"] is None
    assert payload["error_card"]["error_code"] == "target_agent_unavailable"
    assert payload["selected_agent_effective"]["id"] == "agent-demo-model"
