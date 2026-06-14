from tests.support import create_conversation, item_list
from tests.schema_assertions import assert_keys


def test_execution_event_schema(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} event schema")
    _, task, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/tasks",
        {"goal": "Emit one contract event."},
        expected={200, 201, 202},
    )
    task_id = task.get("id") or task.get("task_id")
    _, payload, _ = api_request(
        "GET",
        f"/api/conversations/{conversation['id']}/events?task_id={task_id}&limit=1",
        expected=200,
    )
    event = item_list(payload)[0]
    assert_keys(event, ["id", "conversation_id", "type", "sequence", "payload", "created_at"])
    assert event["conversation_id"] == conversation["id"]
    assert isinstance(event["sequence"], int)
