import json

import services.api.app.agent_runs.service as agent_run_service
from services.api.app.agent_runs.repository import list_run_events
from services.api.app.agent_runs.schema import AgentRunEventDraft
from services.api.app.agents.adapter_health import adapter_health
from services.api.app.conversations.repository import create_conversation, create_message
from services.api.app.orchestration.planner import PlanStepDraft
from services.api.app.orchestration.repository import create_planned_task, get_task
from services.api.app.shared.database import connect
from services.api.app.shared.time import utc_now


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTHUB_PROFILE", "test")
    monkeypatch.setenv("AGENTHUB_ENV", "test")
    monkeypatch.setenv("AGENTHUB_DB_PATH", str(tmp_path / "agent-run-retry.sqlite3"))
    monkeypatch.setenv("AGENTHUB_STAGE_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("AGENTHUB_STAGE_RETRY_BACKOFF_SECONDS", "0")


def _ready_agent(agent_id="agent-retry", provider="custom_openai"):
    now = utc_now()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO agents (
                id, name, provider, avatar, initials, capability_tags_json,
                execution_enabled, configured, health_status,
                enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, NULL, 'AR', ?, 1, 1, 'ready', 1, ?, ?)
            """,
            (
                agent_id,
                "Retry Agent",
                provider,
                json.dumps(["direct_response", "planned_step", "code"], separators=(",", ":")),
                now,
                now,
            ),
        )
    return agent_id


def _message(conversation_id, *, test_run_id="retry-contract"):
    return create_message(
        conversation_id=conversation_id,
        message_type="text",
        content={"text": "Run this stage."},
        mentions=[],
        references=[],
        reply_to_id=None,
        test_run_id=test_run_id,
    )


def _patch_registry(monkeypatch, adapter):
    class FakeRegistry:
        def adapter_for_agent(self, agent):
            return adapter

        def health_for_agent(self, agent):
            return adapter_health(
                provider=str(agent["provider"]),
                adapter_kind="fake",
                configured=True,
                status="ready",
                error_code=None,
                recovery_hint=None,
                capabilities=["direct_response", "planned_step"],
            )

    monkeypatch.setattr(agent_run_service, "AdapterRegistry", FakeRegistry)


def test_transient_stage_failure_retries_before_success(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    agent_id = _ready_agent()
    conversation = create_conversation(
        title="retry",
        mode="group",
        agent_ids=[],
        test_run_id="retry-contract",
    )
    message = _message(str(conversation["id"]))

    class FlakyAdapter:
        calls = 0

        def invoke(self, request):
            self.calls += 1
            if self.calls == 1:
                failure = {
                    "error_code": "backend_network_failed",
                    "message": "temporary network disconnect",
                    "provider": "custom_openai",
                    "recovery_hint": "Reconnect and retry.",
                }
                return [
                    AgentRunEventDraft(type="adapter_error", payload=failure),
                    AgentRunEventDraft(type="run_failed", payload=failure),
                ]
            return [
                AgentRunEventDraft(type="assistant_message_completed", payload={"content_text": "Recovered."}),
                AgentRunEventDraft(type="run_succeeded", payload={"status": "succeeded"}),
            ]

    adapter = FlakyAdapter()
    _patch_registry(monkeypatch, adapter)

    run = agent_run_service.create_direct_response_run_for_message(
        message,
        target_agent_id=agent_id,
        test_run_id="retry-contract",
    )
    events = list_run_events(str(run["id"]), test_run_id="retry-contract")

    assert adapter.calls == 2
    assert run["status"] == "succeeded"
    assert any(event["type"] == "backend_retry" for event in events)
    assert run["assistant_message"]["content"]["text"] == "Recovered."


def test_plan_step_run_updates_step_and_task_status(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    agent_id = _ready_agent()
    conversation = create_conversation(
        title="step status",
        mode="group",
        agent_ids=[],
        test_run_id="retry-contract",
    )
    message = _message(str(conversation["id"]))
    task = create_planned_task(
        conversation_id=str(conversation["id"]),
        message_id=str(message["id"]),
        goal="Run one planned step.",
        steps=[
            PlanStepDraft(
                external_id="step-1",
                kind="implementation",
                title="Implement",
                instruction="Implement this step.",
                assigned_agent_id=agent_id,
                status="assigned",
                dispatch_source="capability",
                dispatch_reason="contract fixture",
                blocked_reason=None,
                depends_on=[],
                expected_output={"kind": "implementation"},
            )
        ],
        test_run_id="retry-contract",
    )
    step_id = str(task["steps"][0]["id"])

    class SuccessfulAdapter:
        def invoke(self, request):
            return [
                AgentRunEventDraft(type="assistant_message_completed", payload={"content_text": "Done."}),
                AgentRunEventDraft(type="run_succeeded", payload={"status": "succeeded"}),
            ]

    _patch_registry(monkeypatch, SuccessfulAdapter())

    run = agent_run_service.create_run_from_body(
        {
            "source_type": "plan_step",
            "plan_step_id": step_id,
            "run_mode": "planned_step",
            "instruction": "Execute the existing planned step.",
        },
        test_run_id="retry-contract",
    )
    refreshed = get_task(str(task["id"]), test_run_id="retry-contract")

    assert run["status"] == "succeeded"
    assert refreshed["status"] == "succeeded"
    assert refreshed["plan"]["status"] == "succeeded"
    assert refreshed["steps"][0]["status"] == "succeeded"
