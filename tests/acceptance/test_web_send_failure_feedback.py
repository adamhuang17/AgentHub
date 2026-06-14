from tests.support import create_conversation, item_list


def _invalid_turn_decision():
    return {
        "decision_type": "direct_response",
        "target_source": "auto_orchestrate",
        "target_agent_id": None,
        "target_agent_ids": "not-a-list",
        "goal": None,
        "steps": [],
        "reason": "Invalid schema for web feedback.",
        "confidence": "high",
        "clarification_question": None,
    }


def test_send_failure_returns_retryable_router_error_and_events_still_load(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} send failure", mode="group")

    status, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "Trigger invalid router output."},
            "turn_decision": _invalid_turn_decision(),
        },
        expected=400,
    )

    assert status == 400
    assert payload["error_code"] == "turn_router_invalid_output"
    assert payload["message"] == "Router output invalid."
    assert payload["recovery_hint"]
    assert payload["retryable"] is True
    assert payload["error_card"]["error_code"] == "turn_router_invalid_output"

    _, events_payload, _ = api_request(
        "GET",
        f"/api/conversations/{conversation['id']}/events",
        expected=200,
    )
    event_types = {event["type"] for event in item_list(events_payload)}
    assert "message.created" in event_types
    assert "router.output_invalid" in event_types
    assert "planner.decision_failed" in event_types
