from http import HTTPStatus

import services.api.app.agent_runs.service as agent_run_service
from services.api.app.agent_runs.schema import AgentRunEventDraft
from services.api.app.agents.adapter_health import adapter_health
from services.api.app.conversations.repository import create_conversation, list_conversation_events
from services.api.app.conversations.routes import handle_post
from services.api.app.orchestration.repository import get_task
from services.api.app.shared.database import connect
from services.api.app.shared.time import utc_now


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTHUB_PROFILE", "test")
    monkeypatch.setenv("AGENTHUB_ENV", "test")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "explicit-dispatch.sqlite3"))
    monkeypatch.setenv("AGENTHUB_TURN_ROUTER_BACKEND", "test")
    monkeypatch.setenv("AGENTHUB_ENABLE_TEST_TURN_ROUTER_BACKEND", "1")
    monkeypatch.setenv("AGENTHUB_MODEL_PROVIDER", "custom_openai")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_BASE", "https://model.example/v1")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_MODEL", "fixture-model")
    monkeypatch.setenv("AGENTHUB_CUSTOM_OPENAI_API_KEY", "fixture-key")


def _make_agent_ready(agent_id, name, provider, tags):
    now = utc_now()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO agents (
                id, name, provider, avatar, initials, capability_tags_json,
                execution_enabled, configured, health_status,
                enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, NULL, 'AI', ?, 1, 1, 'ready', 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                provider = excluded.provider,
                capability_tags_json = excluded.capability_tags_json,
                execution_enabled = 1,
                configured = 1,
                health_status = 'ready',
                enabled = 1,
                updated_at = excluded.updated_at
            """,
            (agent_id, name, provider, _json_tags(tags), now, now),
        )


def _json_tags(tags):
    import json

    return json.dumps(tags, separators=(",", ":"))


def _ready_demo_agents():
    _make_agent_ready("agent-demo-model", "Demo Model Agent", "custom_openai", ["direct_response", "chat", "model"])
    _make_agent_ready("agent-codex-profile", "Codex Profile", "codex", ["implementation", "code", "review", "workspace"])
    _make_agent_ready("agent-claude-profile", "Claude Code Profile", "anthropic", ["code", "reasoning", "documents"])


def _patch_registry(monkeypatch, *, failures=None):
    failures = failures or {}

    class FakeAdapter:
        def __init__(self, agent):
            self.agent = agent

        def invoke(self, request):
            failure = failures.get(request.target_agent_id)
            if failure:
                return [
                    AgentRunEventDraft(type="adapter_error", payload=failure),
                    AgentRunEventDraft(type="run_failed", payload=failure),
                ]
            return [
                AgentRunEventDraft(
                    type="assistant_message_completed",
                    payload={"content_text": f"{request.target_agent_id} handled: {request.instruction}"},
                ),
                AgentRunEventDraft(type="run_succeeded", payload={"status": "succeeded"}),
            ]

        def cancel(self, run_id):
            return {"run_id": run_id, "cancel_requested": False}

    class FakeRegistry:
        def adapter_for_agent(self, agent):
            return FakeAdapter(agent)

        def health_for_agent(self, agent):
            provider = str(agent["provider"])
            return adapter_health(
                provider=provider,
                adapter_kind={
                    "codex": "codex_cli",
                    "anthropic": "claude_code_cli",
                }.get(provider, "custom_openai"),
                configured=True,
                status="ready",
                error_code=None,
                recovery_hint=None,
                capabilities=["direct_response"],
            )

    monkeypatch.setattr(agent_run_service, "AdapterRegistry", FakeRegistry)


def _post(conversation_id, body, test_run_id="explicit-dispatch"):
    return handle_post(f"/api/conversations/{conversation_id}/messages", body, test_run_id)


def _direct_body(text, agent_id):
    return {
        "message_type": "text",
        "content": {"text": text},
        "selected_agent_id": agent_id,
        "force_agent": True,
        "source_surface": "web",
    }


def _router_direct_decision():
    return {
        "decision_type": "direct_response",
        "target_type": "orchestrator",
        "target_source": "auto_orchestrate",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": None,
        "steps": [],
        "reason": "simple answer",
        "confidence": "high",
        "clarification_question": None,
    }


def _plan_decision():
    return {
        "decision_type": "plan_task",
        "target_type": "orchestrator",
        "target_source": "auto_orchestrate",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": "Analyze, implement, and review the demo flow.",
        "steps": [
            {
                "kind": "analysis",
                "objective": "Analyze the flow.",
                "required_capabilities": ["reasoning"],
                "depends_on": [],
                "expected_output": {"kind": "analysis"},
            },
            {
                "kind": "implementation",
                "objective": "Implement the flow.",
                "required_capabilities": ["code"],
                "depends_on": ["step-1"],
                "expected_output": {"kind": "implementation"},
            },
            {
                "kind": "review",
                "objective": "Review the flow.",
                "required_capabilities": ["review"],
                "depends_on": ["step-2"],
                "expected_output": {"kind": "review"},
            },
        ],
        "reason": "complex request",
        "confidence": "high",
        "clarification_question": None,
    }


def test_explicit_selected_demo_model_creates_custom_openai_agent_run(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _ready_demo_agents()
    _patch_registry(monkeypatch)
    conversation = create_conversation(title="demo", mode="group", agent_ids=[], test_run_id="explicit-dispatch")

    status, payload = _post(conversation["id"], _direct_body("Introduce AgentHub in one sentence.", "agent-demo-model"))

    assert status == HTTPStatus.CREATED
    assert payload["dispatch_path"] == "explicit_agent"
    assert payload["agent_run"]["target_agent_id"] == "agent-demo-model"
    assert payload["agent_run"]["status"] == "succeeded"
    assert payload["assistant_message"]["sender_id"] == "agent-demo-model"
    assert payload["selected_agent_effective"]["id"] == "agent-demo-model"


def test_explicit_selected_codex_creates_codex_agent_run(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _ready_demo_agents()
    _patch_registry(monkeypatch)
    conversation = create_conversation(title="codex", mode="group", agent_ids=[], test_run_id="explicit-dispatch")

    status, payload = _post(conversation["id"], _direct_body("Read-only analyze the web flow.", "agent-codex-profile"))

    assert status == HTTPStatus.CREATED
    assert payload["agent_run"]["target_agent_id"] == "agent-codex-profile"
    assert payload["agent_run"]["run_mode"] == "direct_response"
    assert payload["assistant_message"]["sender_id"] == "agent-codex-profile"


def test_explicit_selected_claude_creates_claude_agent_run(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _ready_demo_agents()
    _patch_registry(monkeypatch)
    conversation = create_conversation(title="claude", mode="group", agent_ids=[], test_run_id="explicit-dispatch")

    status, payload = _post(conversation["id"], _direct_body("Read-only analyze reasoning risks.", "agent-claude-profile"))

    assert status == HTTPStatus.CREATED
    assert payload["agent_run"]["target_agent_id"] == "agent-claude-profile"
    assert payload["agent_run"]["status"] == "succeeded"


def test_agent_mention_overrides_invalid_router(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _ready_demo_agents()
    _patch_registry(monkeypatch)
    conversation = create_conversation(title="mention", mode="group", agent_ids=[], test_run_id="explicit-dispatch")

    status, payload = _post(
        conversation["id"],
        {
            "message_type": "text",
            "content": {"text": "@Codex do this directly."},
            "mentions": [{"agent_id": "agent-codex-profile", "display": "Codex Profile"}],
            "turn_decision": {"not": "valid"},
        },
    )

    assert status == HTTPStatus.CREATED
    assert payload["dispatch_path"] == "explicit_agent"
    assert payload["agent_run"]["target_agent_id"] == "agent-codex-profile"
    assert payload["task"] is None


def test_worker_private_codex_defaults_to_codex_without_mention(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _ready_demo_agents()
    _patch_registry(monkeypatch)
    conversation = create_conversation(
        title="Codex worker",
        mode="single",
        agent_ids=["agent-codex-profile"],
        test_run_id="explicit-dispatch",
    )

    status, payload = _post(
        conversation["id"],
        {"message_type": "text", "content": {"text": "Read-only inspect the project."}},
    )

    assert status == HTTPStatus.CREATED
    assert payload["dispatch_path"] == "explicit_agent"
    assert payload["agent_run"]["target_agent_id"] == "agent-codex-profile"


def test_project_group_without_agent_uses_router_and_default_model(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _ready_demo_agents()
    _patch_registry(monkeypatch)
    conversation = create_conversation(title="project", mode="group", agent_ids=[], test_run_id="explicit-dispatch")

    status, payload = _post(
        conversation["id"],
        {
            "message_type": "text",
            "content": {"text": "Answer normally."},
            "turn_decision": _router_direct_decision(),
        },
    )

    assert status == HTTPStatus.CREATED
    assert payload["dispatch_path"] == "router_direct_response"
    assert payload["agent_run"]["target_agent_id"] == "agent-demo-model"
    assert payload["assistant_message"]["sender_id"] == "agent-demo-model"


def test_project_group_plan_request_promotes_router_direct_response_to_plan(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _ready_demo_agents()
    conversation = create_conversation(title="project plan", mode="group", agent_ids=[], test_run_id="explicit-dispatch")

    status, payload = _post(
        conversation["id"],
        {
            "message_type": "text",
            "content": {"text": "请分析 AgentHub 演示链路，并拆成分析、实现、评审三步。"},
            "turn_decision": _router_direct_decision(),
        },
    )
    task = get_task(payload["task_id"], test_run_id="explicit-dispatch")

    assert status == HTTPStatus.CREATED
    assert payload["dispatch_path"] == "router_plan_task"
    assert payload["agent_run"] is None
    assert any(step["status"] == "assigned" for step in task["steps"])
    assert not all(step["status"] == "blocked" for step in task["steps"])
    assert task["steps"][1]["assigned_agent_id"] == "agent-codex-profile"


def test_configured_agents_ready_plan_task_has_assigned_steps(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _ready_demo_agents()
    conversation = create_conversation(title="plan", mode="group", agent_ids=[], test_run_id="explicit-dispatch")

    status, payload = _post(
        conversation["id"],
        {
            "message_type": "text",
            "content": {"text": "Break this into analysis, implementation, review."},
            "turn_decision": _plan_decision(),
        },
    )
    task = get_task(payload["task_id"], test_run_id="explicit-dispatch")
    steps = task["steps"]

    assert status == HTTPStatus.CREATED
    assert payload["dispatch_path"] == "router_plan_task"
    assert any(step["status"] == "assigned" for step in steps)
    assert not all(step["status"] == "blocked" for step in steps)
    assert steps[0]["assigned_agent_id"] in {"agent-claude-profile", "agent-demo-model"}
    assert steps[1]["assigned_agent_id"] == "agent-codex-profile"


def test_codex_run_failure_maps_to_agent_run_failed_card(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _ready_demo_agents()
    _patch_registry(
        monkeypatch,
        failures={
            "agent-codex-profile": {
                "error_code": "codex_cli_failed",
                "message": "Codex CLI failed.",
                "provider": "codex",
                "recovery_hint": "Inspect Codex authentication.",
                "exit_code": 7,
                "stderr_summary": "codex stderr",
            }
        },
    )
    conversation = create_conversation(title="codex fail", mode="group", agent_ids=[], test_run_id="explicit-dispatch")

    status, payload = _post(conversation["id"], _direct_body("Read-only inspect.", "agent-codex-profile"))

    assert status == HTTPStatus.CREATED
    assert payload["dispatch_path"] == "failed"
    assert payload["agent_run"]["status"] == "failed"
    assert payload["agent_run"]["error_code"] == "codex_cli_failed"
    assert payload["error_card"]["error_code"] == "codex_cli_failed"
    assert payload["error_card"]["stderr_summary"] == "codex stderr"
    events = list_conversation_events(conversation["id"], test_run_id="explicit-dispatch")
    assert any(event["type"] == "agent_run.failed" for event in events)
    assert not any(event["type"] == "step.blocked" for event in events)


def test_router_invalid_returns_error_card_with_saved_user_message(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _ready_demo_agents()
    conversation = create_conversation(title="router invalid", mode="group", agent_ids=[], test_run_id="explicit-dispatch")

    status, payload = _post(
        conversation["id"],
        {
            "message_type": "text",
            "content": {"text": "Route this."},
            "turn_decision": {**_router_direct_decision(), "target_agent_ids": "bad"},
        },
    )

    assert status == HTTPStatus.CREATED
    assert payload["dispatch_path"] == "failed"
    assert payload["message"]["content"]["text"] == "Route this."
    assert payload["error_card"]["error_code"] == "turn_router_invalid_output"
    assert payload["error_message"] == "Router output invalid."
    assert payload["events_summary"]["types"]["router.output_invalid"] == 1
