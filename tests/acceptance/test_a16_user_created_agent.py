from tests.support import create_conversation, item_list, post_message, task_from_message, wait_task


def test_a16_user_created_agent_can_be_mentioned_and_dispatched(api_request, unique_id):
    _, agent, _ = api_request(
        "POST",
        "/api/agents",
        {
            "name": f"{unique_id}-custom-reviewer",
            "kind": "custom",
            "enabled": True,
            "system_prompt": "You are a strict acceptance reviewer. Return concise findings only.",
            "model": {"provider": "default", "model": "default"},
            "allowed_tools": ["artifact.read", "artifact.write"],
            "capability_tags": ["acceptance-review", "custom-agent"],
        },
        expected={200, 201},
    )
    assert agent.get("id"), agent
    assert agent.get("kind") == "custom"
    assert "acceptance-review" in agent.get("capability_tags", [])

    _, agents_payload, _ = api_request("GET", "/api/agents?kind=custom&enabled=true", expected=200)
    agents = item_list(agents_payload)
    assert any(item.get("id") == agent["id"] for item in agents), agents

    conversation = create_conversation(api_request, f"{unique_id} custom agent", agent_ids=[agent["id"]])
    message = post_message(
        api_request,
        conversation["id"],
        f"@{agent['name']} review this one-line requirement.",
        mentions=[{"agent_id": agent["id"], "label": agent["name"]}],
    )
    task = wait_task(api_request, task_from_message(message), terminal=("succeeded", "failed"))
    task_id = task.get("id") or task.get("task_id")

    _, plan, _ = api_request("GET", f"/api/tasks/{task_id}/plan", expected=200)
    steps = plan.get("steps", [])
    assert steps, plan
    assert any(step.get("assigned_agent_id") == agent["id"] for step in steps), plan
    assert any("mention" in (step.get("dispatch_reason") or "").lower() for step in steps), plan
    if task.get("status") == "failed":
        assert task.get("error_code")
        assert task.get("message")
