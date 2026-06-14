from tests.support import (
    assert_no_run_succeeded,
    conversation_messages,
    create_conversation,
    enabled_agents,
    item_list,
    post_message,
)


def test_a7_agent_adapter_contract(api_request, unique_id):
    agents = enabled_agents(api_request, minimum=2)
    conversation = create_conversation(api_request, f"{unique_id} adapter contract")
    message = post_message(
        api_request,
        conversation["id"],
        "Create direct response runs through the unified A7 run endpoint.",
    )

    base_request = {
        "source_type": "message",
        "source_message_id": message["id"],
        "run_mode": "direct_response",
        "instruction": "Return adapter identity and capabilities through the normal run event stream.",
        "context_bundle": {
            "recent_messages": [],
            "pinned_context": [],
            "artifact_refs": [],
            "constraints": ["Do not modify files for this contract run."],
        },
        "workspace_ref": {"type": "managed", "conversation_id": conversation["id"]},
        "allowed_tools": [],
        "expected_artifacts": [],
    }

    run_ids = []
    for agent in agents[:2]:
        _, payload, _ = api_request(
            "POST",
            "/api/runs",
            {**base_request, "target_agent_id": agent["id"]},
            expected=201,
        )
        assert payload["id"]
        assert payload["source_type"] == "message"
        assert payload["source_message_id"] == message["id"]
        assert payload["target_agent_id"] == agent["id"]
        assert payload["run_mode"] == "direct_response"
        assert payload["status"] == "failed"
        assert payload["error_code"] == "provider_not_configured"
        assert_no_run_succeeded(payload)
        run_ids.append(payload["id"])

    for run_id in run_ids:
        _, payload, _ = api_request("GET", f"/api/runs/{run_id}/events", expected=200)
        events = item_list(payload)
        event_types = [event["type"] for event in events]

        assert event_types == ["run_created", "run_started", "provider_not_configured", "run_failed"]
        assert [event["sequence"] for event in events] == [1, 2, 3, 4]
        assert events[2]["payload"]["error_code"] == "provider_not_configured"
        assert events[3]["payload"]["error_code"] == "provider_not_configured"
        assert_no_run_succeeded(events)

    assert len(conversation_messages(api_request, conversation["id"])) == 1

    _, legacy_payload, _ = api_request(
        "POST",
        f"/api/agents/{agents[0]['id']}/runs",
        {**base_request, "target_agent_id": agents[0]["id"]},
        expected=404,
    )
    assert legacy_payload["error"] == "not_found"
