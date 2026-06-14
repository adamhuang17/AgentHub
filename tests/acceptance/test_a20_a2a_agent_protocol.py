from tests.support import create_conversation, enabled_agents, item_list


def test_a20_a2a_message_envelope_is_persistent_and_routable(api_request, unique_id):
    agents = enabled_agents(api_request, minimum=2)[:2]
    conversation = create_conversation(
        api_request,
        f"{unique_id} a2a protocol",
        agent_ids=[agent["id"] for agent in agents],
    )
    body = {
        "conversation_id": conversation["id"],
        "from_agent_id": agents[0]["id"],
        "to_agent_id": agents[1]["id"],
        "message_type": "delegation",
        "correlation_id": f"{unique_id}-a2a",
        "payload": {
            "subject": "Review delegated artifact plan",
            "body": "Please review the proposed artifact strategy before execution.",
        },
    }
    _, envelope, _ = api_request("POST", "/api/a2a/messages", body, expected={200, 201, 202})
    for key in ["id", "conversation_id", "from_agent_id", "to_agent_id", "message_type", "correlation_id", "payload"]:
        assert key in envelope, envelope
    assert envelope["conversation_id"] == conversation["id"]
    assert envelope["from_agent_id"] == agents[0]["id"]
    assert envelope["to_agent_id"] == agents[1]["id"]
    assert envelope["correlation_id"] == body["correlation_id"]

    _, mailbox_payload, _ = api_request(
        "GET",
        f"/api/a2a/messages?conversation_id={conversation['id']}&to_agent_id={agents[1]['id']}",
        expected=200,
    )
    mailbox = item_list(mailbox_payload)
    assert any(message.get("id") == envelope["id"] for message in mailbox), mailbox

    _, events_payload, _ = api_request(
        "GET",
        f"/api/conversations/{conversation['id']}/events?type=a2a.message.created",
        expected=200,
    )
    events = item_list(events_payload)
    assert any(event.get("payload", {}).get("a2a_message_id") == envelope["id"] for event in events), events
