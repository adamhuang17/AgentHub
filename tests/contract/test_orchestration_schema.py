from tests.support import create_conversation, enabled_agents, item_list, post_message, task_from_message
from tests.schema_assertions import assert_keys


def test_mention_dispatch_creates_planned_task_schema(api_request, unique_id):
    agent = enabled_agents(api_request, minimum=1)[0]
    conversation = create_conversation(
        api_request,
        f"{unique_id} orchestration schema",
        agent_ids=[agent["id"]],
    )
    message = post_message(
        api_request,
        conversation["id"],
        f"@{agent['name']} prepare a plan step",
        mentions=[{"agent_id": agent["id"], "display": agent["name"]}],
    )

    task_id = task_from_message(message)
    _, task, _ = api_request("GET", f"/api/tasks/{task_id}", expected=200)
    assert_keys(task, ["id", "conversation_id", "created_by_message_id", "goal", "status", "plan", "steps"])
    assert task["status"] == "planned"
    assert task["created_by_message_id"] == message["id"]

    steps = task["steps"]
    assert len(steps) == 1
    step = steps[0]
    assert step["kind"] == "agent_message"
    assert step["assigned_agent_id"] == agent["id"]
    assert step["status"] == "assigned"
    assert step["dispatch_source"] == "mention"
    assert "mentioned" in step["dispatch_reason"].lower()

    _, plan, _ = api_request("GET", f"/api/tasks/{task_id}/plan", expected=200)
    assert plan["status"] == "ready"
    assert plan["steps"][0]["id"] == step["id"]

    _, plan_by_id, _ = api_request("GET", f"/api/plans/{plan['id']}", expected=200)
    assert plan_by_id["id"] == plan["id"]

    _, task_list, _ = api_request("GET", f"/api/conversations/{conversation['id']}/tasks", expected=200)
    assert task_id in {item["id"] for item in item_list(task_list)}


def test_unknown_mentioned_agent_returns_error_without_fallback(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} unknown mention")
    _, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "@MissingAgent should not be silently rerouted"},
            "mentions": [{"agent_id": "missing-agent", "display": "MissingAgent"}],
        },
        expected=400,
    )
    assert payload["error"] == "validation_error"
    assert "missing-agent" in payload["message"]

    _, task_list, _ = api_request("GET", f"/api/conversations/{conversation['id']}/tasks", expected=200)
    assert item_list(task_list) == []
