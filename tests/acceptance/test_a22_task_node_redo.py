from tests.support import create_conversation, item_list, wait_until


def test_a22_task_node_can_be_rewritten_and_redone_without_losing_lineage(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} node redo")
    _, task, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/tasks",
        {
            "goal": "Create a two-step plan, run the first step, and keep task-node lineage durable.",
            "acceptance": {"min_steps": 2, "requires_step_lineage": True},
        },
        expected={200, 201, 202},
    )
    task_id = task.get("id") or task.get("task_id")
    assert task_id

    def plan_probe():
        _, payload, _ = api_request("GET", f"/api/tasks/{task_id}/plan", expected=200)
        steps = payload.get("steps", [])
        return payload if steps else None

    plan = wait_until(plan_probe, timeout=90, label="task plan with steps")
    step = plan["steps"][0]
    step_id = step.get("id") or step.get("step_id")
    assert step_id, step

    _, redo, _ = api_request(
        "POST",
        f"/api/tasks/{task_id}/steps/{step_id}/redo",
        {
            "edited_prompt": "Redo this step with a stronger persistence-first implementation strategy.",
            "reason": "user edited prompt after reviewing the previous node",
        },
        expected={200, 201, 202},
    )
    assert redo.get("task_id") == task_id
    assert redo.get("previous_step_id") == step_id
    assert redo.get("new_step_id") and redo.get("new_step_id") != step_id
    assert redo.get("lineage_id") or redo.get("redo_id"), redo

    _, runs_payload, _ = api_request("GET", f"/api/tasks/{task_id}/steps/{step_id}/runs", expected=200)
    old_runs = item_list(runs_payload)
    assert old_runs, old_runs
    assert all(run.get("deleted") is not True for run in old_runs), old_runs

    _, lineage_payload, _ = api_request("GET", f"/api/tasks/{task_id}/lineage", expected=200)
    lineage_items = item_list(lineage_payload)
    assert any(item.get("step_id") == step_id for item in lineage_items), lineage_items
    assert any(item.get("step_id") == redo["new_step_id"] for item in lineage_items), lineage_items
