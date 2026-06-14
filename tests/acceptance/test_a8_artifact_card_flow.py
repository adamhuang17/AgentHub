from http import HTTPStatus
from pathlib import Path

import pytest

import services.api.app.agent_runs.service as agent_run_service
from services.api.app.agent_runs.repository import list_run_events
from services.api.app.agent_runs.schema import AgentRunEventDraft
from services.api.app.agents.adapter_health import adapter_health
from services.api.app.artifacts.repository import list_artifacts
from services.api.app.artifacts.routes import handle_get as handle_artifacts_get
from services.api.app.conversations.repository import create_conversation, create_message, list_messages
from services.api.app.shared.database import connect
from services.api.app.shared.time import utc_now


def _store_dir(test_run_id):
    return Path("var") / "test-artifacts" / test_run_id


def _insert_ready_agent(agent_id):
    now = utc_now()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO agents (
                id, name, provider, avatar, initials, capability_tags_json,
                execution_enabled, configured, health_status,
                enabled, created_at, updated_at
            )
            VALUES (?, ?, 'openai', NULL, 'A8', '["direct_response","documents"]', 1, 1, 'configured', 1, ?, ?)
            """,
            (agent_id, f"{agent_id} Agent", now, now),
        )


def _conversation_and_message(agent_id, test_run_id):
    conversation = create_conversation(
        title=f"{test_run_id} artifact card",
        mode="private_agent",
        agent_ids=[agent_id],
        test_run_id=test_run_id,
    )
    message = create_message(
        conversation_id=str(conversation["id"]),
        message_type="text",
        content={"text": "Create a persistent markdown artifact for A8."},
        mentions=[],
        references=[],
        reply_to_id=None,
        test_run_id=test_run_id,
    )
    return conversation, message


def _run_payload(agent_id, message, unique_id):
    return {
        "source_type": "message",
        "source_message_id": message["id"],
        "target_agent_id": agent_id,
        "run_mode": "direct_response",
        "instruction": f"Create an A8 artifact note for {unique_id}.",
        "context_bundle": {"recent_messages": [], "artifact_refs": []},
        "workspace_ref": None,
        "allowed_tools": [],
        "expected_artifacts": [
            {
                "type": "document",
                "title": f"Engineering Acceptance Note {unique_id}",
                "mime_type": "text/markdown",
            }
        ],
    }


def _patch_registry(monkeypatch, events):
    class FakeAdapter:
        adapter_id = "a8-fixture"

        def invoke(self, request):
            del request
            return list(events)

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


def test_a8_direct_response_success_creates_artifact_card_flow(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-a8-success"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    agent_id = f"agent-{test_run_id}"
    _insert_ready_agent(agent_id)
    conversation, message = _conversation_and_message(agent_id, test_run_id)
    output = f"# A8 Artifact\n\nPersistent assistant output for {unique_id}."
    _patch_registry(
        monkeypatch,
        [
            AgentRunEventDraft(type="assistant_message_completed", payload={"content_text": output}),
            AgentRunEventDraft(type="run_succeeded", payload={"status": "succeeded"}),
        ],
    )

    run = agent_run_service.create_run_from_body(_run_payload(agent_id, message, unique_id), test_run_id=test_run_id)

    artifacts = list_artifacts(test_run_id=test_run_id, conversation_id=str(conversation["id"]))
    messages = list_messages(str(conversation["id"]), test_run_id=test_run_id)
    assistant_messages = [item for item in messages if item["sender_type"] == "assistant"]
    events = list_run_events(str(run["id"]), test_run_id=test_run_id)

    assert run["status"] == "succeeded"
    assert run["artifact"]["id"] == artifacts[0]["id"]
    assert len(artifacts) == 1
    assert artifacts[0]["created_by_run_id"] == run["id"]
    assert artifacts[0]["conversation_id"] == conversation["id"]
    assert artifacts[0]["task_id"] is None
    assert artifacts[0]["type"] == "document"
    assert artifacts[0]["mime_type"] == "text/markdown"
    assert artifacts[0]["storage_key"]
    assert artifacts[0]["checksum"].startswith("sha256:")
    assert [event["type"] for event in events] == [
        "run_created",
        "run_started",
        "assistant_message_completed",
        "run_succeeded",
    ]
    assert len(assistant_messages) == 1
    assistant = assistant_messages[0]
    assert assistant["created_by_run_id"] == run["id"]
    assert assistant["content"]["text"] == output
    assert assistant["references"][0]["artifact_id"] == artifacts[0]["id"]
    assert assistant["artifact_card"]["artifact_id"] == artifacts[0]["id"]

    status, versions_payload = handle_artifacts_get(
        f"/api/artifacts/{artifacts[0]['id']}/versions",
        {},
        test_run_id,
    )
    assert status == HTTPStatus.OK
    assert versions_payload["items"][0]["checksum"] == artifacts[0]["checksum"]

    status, content_payload = handle_artifacts_get(
        f"/api/artifacts/{artifacts[0]['id']}/content",
        {},
        test_run_id,
    )
    assert status == HTTPStatus.OK
    assert content_payload["content"] == output
    assert content_payload["checksum"] == versions_payload["items"][0]["checksum"]


@pytest.mark.parametrize(
    ("events", "error_code"),
    [
        (
            [
                AgentRunEventDraft(
                    type="adapter_error",
                    payload={
                        "error_code": "backend_auth_failed",
                        "message": "Auth failed.",
                        "provider": "openai",
                    },
                ),
                AgentRunEventDraft(
                    type="run_failed",
                    payload={
                        "error_code": "backend_auth_failed",
                        "message": "Auth failed.",
                        "provider": "openai",
                    },
                ),
            ],
            "backend_auth_failed",
        ),
        (
            [
                AgentRunEventDraft(
                    type="run_timed_out",
                    payload={
                        "error_code": "run_timed_out",
                        "message": "Adapter timed out.",
                        "provider": "openai",
                    },
                )
            ],
            "run_timed_out",
        ),
    ],
)
def test_a8_failed_auth_or_timed_out_run_creates_no_artifact(monkeypatch, unique_id, events, error_code):
    test_run_id = f"{unique_id}-a8-failure"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    agent_id = f"agent-{test_run_id}"
    _insert_ready_agent(agent_id)
    conversation, message = _conversation_and_message(agent_id, test_run_id)
    _patch_registry(monkeypatch, events)

    run = agent_run_service.create_run_from_body(_run_payload(agent_id, message, unique_id), test_run_id=test_run_id)

    assert run["status"] == "failed"
    assert run["error_code"] == error_code
    assert list_artifacts(test_run_id=test_run_id, conversation_id=str(conversation["id"])) == []
    assert list_artifacts(test_run_id=test_run_id, created_by_run_id=str(run["id"])) == []
    assert [item["sender_type"] for item in list_messages(str(conversation["id"]), test_run_id=test_run_id)] == ["user"]
    assert "run_succeeded" not in [event["type"] for event in list_run_events(str(run["id"]), test_run_id=test_run_id)]
