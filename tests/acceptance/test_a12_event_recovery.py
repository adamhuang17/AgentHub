from urllib import parse

from tests.support import create_conversation, item_list, read_sse_events, wait_task


def test_a12_event_recovery(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} event recovery")
    _, task, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/tasks",
        {
            "goal": "Run a recoverable acceptance task that emits at least four durable execution events.",
            "acceptance": {"requires_sse": True, "min_event_count": 4},
        },
        expected={200, 201, 202},
    )
    task_id = task.get("id") or task.get("task_id")
    assert task_id

    stream_path = (
        f"/api/conversations/{conversation['id']}/events/stream?"
        f"task_id={parse.quote(task_id)}&limit=1"
    )
    first_events = read_sse_events(stream_path, min_events=1, timeout=30)
    first_sequence = first_events[-1]["sequence"]
    assert isinstance(first_sequence, int), first_events[-1]

    reconnect_path = (
        f"/api/conversations/{conversation['id']}/events/stream?"
        f"task_id={parse.quote(task_id)}&after={first_sequence}"
    )
    replay_events = read_sse_events(reconnect_path, min_events=1, timeout=45)
    assert all(event["sequence"] > first_sequence for event in replay_events), replay_events
    assert len({event["sequence"] for event in replay_events}) == len(replay_events), replay_events

    final_task = wait_task(api_request, task_id)
    _, final_events_payload, _ = api_request(
        "GET",
        f"/api/conversations/{conversation['id']}/events?task_id={task_id}",
        expected=200,
    )
    final_events = item_list(final_events_payload)
    assert final_events[-1]["payload"].get("task_status") == final_task["status"] or final_events[-1]["type"] in {
        "task.succeeded",
        "task.failed",
        "task.completed",
    }
