from tests.support import api_call, create_conversation, enabled_agents, item_list, post_message


def test_post_pin_message_then_context_visible(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} core pin message")
    message = post_message(api_request, conversation["id"], f"{unique_id} important pinned message")

    _, pin, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/pin",
        {"source_type": "message", "source_id": message["id"], "note": "demo pin"},
        expected=201,
    )
    _, context, _ = api_request("GET", f"/api/conversations/{conversation['id']}/context", expected=200)

    assert pin["source_id"] == message["id"]
    assert context["pinned_context"][0]["source_id"] == message["id"]
    assert context["pinned_context"][0]["resolved"]["text"].endswith("important pinned message")


def test_post_pin_artifact_then_context_has_artifact_ref(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} core pin artifact")
    _, artifact, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation["id"],
            "type": "document",
            "title": "Pinned.md",
            "mime_type": "text/markdown",
            "content": "# Pinned",
        },
        expected=201,
    )

    api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/pin",
        {"source_type": "artifact", "source_id": artifact["id"]},
        expected=201,
    )
    _, context, _ = api_request("GET", f"/api/conversations/{conversation['id']}/context", expected=200)

    assert any(item["artifact_id"] == artifact["id"] for item in context["artifact_refs"])
    assert context["pinned_context"][0]["resolved"]["artifact_id"] == artifact["id"]


def test_direct_response_run_uses_context_summary(api_request, unique_id):
    agent = enabled_agents(api_request, minimum=1)[0]
    conversation = create_conversation(
        api_request,
        f"{unique_id} direct context",
        mode="single",
        agent_ids=[agent["id"]],
    )
    message = post_message(api_request, conversation["id"], "Use the current context.")

    _, run, _ = api_request(
        "POST",
        "/api/runs",
        {
            "source_type": "message",
            "source_message_id": message["id"],
            "target_agent_id": agent["id"],
            "run_mode": "direct_response",
            "instruction": "Reply if configured.",
            "context_bundle": {},
            "workspace_ref": None,
            "allowed_tools": [],
            "expected_artifacts": [],
        },
        expected=201,
    )
    _, events_payload, _ = api_request("GET", f"/api/conversations/{conversation['id']}/events", expected=200)
    events = item_list(events_payload)
    created = next(event for event in events if event["type"] == "agent_run.created")

    assert run["context_summary"]["recent_message_count"] >= 1
    assert created["payload"]["context_summary"]["recent_message_count"] >= 1
    assert any(event["type"] == "context.built" for event in events)

