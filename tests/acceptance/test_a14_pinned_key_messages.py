import json

from tests.support import create_conversation, post_message, task_from_message, wait_task


def test_a14_pinned_key_messages_enter_context(api_request, unique_id):
    token = f"{unique_id}-pinned-requirement"
    conversation = create_conversation(api_request, f"{unique_id} pinned messages")
    message = post_message(
        api_request,
        conversation["id"],
        f"Key requirement to pin: every deployment note must mention {token}.",
    )

    _, pin, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/pin",
        {"source_type": "message", "source_id": message["id"], "note": "acceptance key requirement"},
        expected=201,
    )
    assert pin.get("source_type") == "message"
    assert pin.get("source_id") == message["id"]
    assert pin.get("conversation_id") == conversation["id"]
    assert pin.get("created_at")

    _, context, _ = api_request(
        "GET",
        f"/api/conversations/{conversation['id']}/context?include_pins=true",
        expected=200,
    )
    context_blob = json.dumps(context, ensure_ascii=False)
    assert token in context_blob
    assert message["id"] in context_blob

    task_message = post_message(
        api_request,
        conversation["id"],
        "Use pinned key requirements to draft a short deployment note.",
        turn_decision={
            "decision_type": "plan_task",
            "target_type": "orchestrator",
            "target_source": "auto_orchestrate",
            "target_agent_id": None,
            "target_agent_ids": [],
            "goal": "Draft a short deployment note from pinned key requirements.",
            "steps": [
                {
                    "kind": "analysis",
                    "objective": "Use pinned key requirements.",
                    "required_capabilities": ["missing-a14-capability"],
                    "depends_on": [],
                    "expected_output": {"kind": "analysis"},
                }
            ],
            "reason": "A14 pinned context acceptance fixture",
            "confidence": "high",
            "clarification_question": None,
        },
    )
    task = wait_task(api_request, task_from_message(task_message), terminal=("planned",))
    task_id = task.get("id") or task.get("task_id")
    _, task_context, _ = api_request("GET", f"/api/tasks/{task_id}/context", expected=200)
    task_context_blob = json.dumps(task_context, ensure_ascii=False)
    assert token in task_context_blob
    assert message["id"] in task_context_blob
