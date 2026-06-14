from tests.support import create_conversation, item_list, post_message, task_from_message, wait_task


def test_a24_task_trace_links_message_plan_agent_events_and_artifacts(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} task trace")
    message = post_message(
        api_request,
        conversation["id"],
        "Create a tiny traceable artifact and expose every module hop in the task trace.",
    )
    task = wait_task(api_request, task_from_message(message), terminal=("succeeded", "failed"), timeout=180)
    task_id = task.get("id") or task.get("task_id")

    _, trace_payload, _ = api_request("GET", f"/api/tasks/{task_id}/trace", expected=200)
    trace_items = item_list(trace_payload)
    assert trace_items, trace_payload
    modules = {item.get("module") for item in trace_items}
    for required in {"conversations", "orchestration", "execution"}:
        assert required in modules, trace_items
    assert "agents" in modules or "model_router" in modules, trace_items

    assert any(item.get("message_id") == message["id"] for item in trace_items), trace_items
    assert any(item.get("task_id") == task_id for item in trace_items), trace_items
    assert all(item.get("created_at") for item in trace_items), trace_items
    assert all(item.get("trace_id") for item in trace_items), trace_items

    if task.get("status") == "succeeded":
        assert "artifacts" in modules, trace_items
    else:
        assert any(item.get("error_code") for item in trace_items), trace_items
