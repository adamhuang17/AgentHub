from tests.support import (
    assert_no_run_succeeded,
    conversation_messages,
    conversation_tasks,
    create_conversation,
    enabled_agents,
    item_list,
    post_message,
)
from tests.schema_assertions import assert_keys


def test_agent_run_protocol(api_request, unique_id):
    agent = enabled_agents(api_request, minimum=1)[0]
    conversation = create_conversation(api_request, f"{unique_id} agent run protocol")
    message = post_message(api_request, conversation["id"], "Source message for AgentRun protocol.")
    request_payload = {
        "source_type": "message",
        "source_message_id": message["id"],
        "target_agent_id": agent["id"],
        "run_mode": "direct_response",
        "instruction": "Contract check for AgentRunRequest.",
        "context_bundle": {"recent_messages": [], "pinned_context": [], "artifact_refs": []},
        "workspace_ref": {"type": "managed", "conversation_id": conversation["id"]},
        "allowed_tools": [],
        "expected_artifacts": [],
    }
    _, payload, _ = api_request("POST", "/api/runs", request_payload, expected=201)
    assert_keys(
        payload,
        [
            "id",
            "conversation_id",
            "source_type",
            "source_message_id",
            "target_agent_id",
            "run_mode",
            "status",
            "error_code",
        ],
    )
    assert payload["conversation_id"] == conversation["id"]
    assert payload["source_type"] == "message"
    assert payload["source_message_id"] == message["id"]
    assert payload["target_agent_id"] == agent["id"]
    assert payload["run_mode"] == "direct_response"
    assert payload["status"] == "failed"
    assert payload["error_code"] == "provider_not_configured"
    assert_no_run_succeeded(payload)

    _, events_payload, _ = api_request("GET", f"/api/runs/{payload['id']}/events", expected=200)
    events = item_list(events_payload)
    assert [event["sequence"] for event in events] == [1, 2, 3, 4]
    assert [event["type"] for event in events] == [
        "run_created",
        "run_started",
        "provider_not_configured",
        "run_failed",
    ]
    assert_no_run_succeeded(events)


def test_plain_message_without_planner_or_turn_decision_is_message_only(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} plain message")

    message = post_message(api_request, conversation["id"], "Plain message must not auto-plan in test env.")

    assert message["id"]
    assert "task_id" not in message
    assert "run_id" not in message
    assert conversation_tasks(api_request, conversation["id"]) == []
    assert len(conversation_messages(api_request, conversation["id"])) == 1
