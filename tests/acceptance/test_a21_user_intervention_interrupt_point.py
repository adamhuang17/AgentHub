from tests.support import create_conversation, item_list, wait_until


def test_a21_user_intervention_is_queued_until_interrupt_point(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} intervention")
    _, task, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/tasks",
        {
            "goal": "Run a multi-step implementation task with at least one durable interruption point.",
            "acceptance": {"requires_interruption_point": True, "min_steps": 2},
        },
        expected={200, 201, 202},
    )
    task_id = task.get("id") or task.get("task_id")
    assert task_id

    _, intervention, _ = api_request(
        "POST",
        f"/api/tasks/{task_id}/interventions",
        {
            "kind": "supplemental_context",
            "content": "Before the next step, prefer a database-backed queue over process memory.",
            "apply_at": "next_interrupt_point",
        },
        expected={200, 201, 202},
    )
    assert intervention.get("id"), intervention
    assert intervention.get("task_id") == task_id
    assert intervention.get("state") in {"queued", "waiting_interrupt_point", "applied"}, intervention
    assert intervention.get("apply_at") == "next_interrupt_point"

    def probe():
        _, payload, _ = api_request("GET", f"/api/tasks/{task_id}/interventions", expected=200)
        interventions = item_list(payload)
        current = next((item for item in interventions if item.get("id") == intervention["id"]), None)
        if current and current.get("state") in {"waiting_user_context", "applied"}:
            return current
        return None

    applied = wait_until(probe, timeout=120, label="intervention reaches interrupt point")
    assert applied.get("interrupt_point_id") or applied.get("applied_to_step_id"), applied

    _, events_payload, _ = api_request(
        "GET",
        f"/api/conversations/{conversation['id']}/events?task_id={task_id}&type=task.intervention",
        expected=200,
    )
    events = item_list(events_payload)
    assert any(event.get("payload", {}).get("intervention_id") == intervention["id"] for event in events), events
