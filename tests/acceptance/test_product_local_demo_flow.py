from tests.support import create_conversation, enabled_agents, item_list


def _direct_response_decision(agent_id):
    return {
        "decision_type": "direct_response",
        "target_type": "agent",
        "target_source": "private_chat",
        "target_agent_id": agent_id,
        "target_agent_ids": [agent_id],
        "goal": None,
        "steps": [],
        "reason": "Local demo direct response route.",
        "confidence": "high",
        "clarification_question": None,
    }


def test_product_local_demo_flow(api_request, unique_id):
    agents = enabled_agents(api_request, minimum=1)
    agent = agents[0]

    _, list_payload, _ = api_request("GET", "/api/conversations", expected=200)
    assert isinstance(item_list(list_payload), list)
    _, agent_payload, _ = api_request("GET", "/api/agents", expected=200)
    assert item_list(agent_payload)

    conversation = create_conversation(
        api_request,
        f"{unique_id} local demo",
        mode="single",
        agent_ids=[agent["id"]],
    )
    _, message, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "Hello from the local product demo."},
            "turn_decision": _direct_response_decision(agent["id"]),
        },
        expected=201,
    )

    _, messages_payload, _ = api_request(
        "GET",
        f"/api/conversations/{conversation['id']}/messages",
        expected=200,
    )
    messages = item_list(messages_payload)
    assert any(item["id"] == message["id"] for item in messages)

    _, events_payload, _ = api_request(
        "GET",
        f"/api/conversations/{conversation['id']}/events",
        expected=200,
    )
    events = item_list(events_payload)
    event_types = {event["type"] for event in events}
    assert "message.created" in event_types
    assert "planner.decision_created" in event_types
    assert "agent_run.created" in event_types
    assert {"agent_run.failed", "agent_run.succeeded"} & event_types
    context_built_before_get = sum(1 for event in events if event["type"] == "context.built")

    api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/pin",
        {"source_type": "message", "source_id": message["id"]},
        expected=201,
    )
    _, context, _ = api_request("GET", f"/api/conversations/{conversation['id']}/context", expected=200)
    assert context["conversation_id"] == conversation["id"]
    assert context["context_summary"]["pinned_count"] == 1
    assert context["constraints"]["max_recent_messages"] >= 1

    _, events_after_context, _ = api_request(
        "GET",
        f"/api/conversations/{conversation['id']}/events",
        expected=200,
    )
    assert (
        sum(1 for event in item_list(events_after_context) if event["type"] == "context.built")
        == context_built_before_get
    )
