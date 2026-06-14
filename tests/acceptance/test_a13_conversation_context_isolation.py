import json

from tests.support import create_conversation, post_message


def test_a13_conversation_context_isolation(api_request, unique_id):
    left_token = f"{unique_id}-left-context"
    right_token = f"{unique_id}-right-context"
    left = create_conversation(api_request, f"{unique_id} context left")
    right = create_conversation(api_request, f"{unique_id} context right")

    post_message(api_request, left["id"], f"Remember only this conversation token: {left_token}")
    post_message(api_request, right["id"], f"Remember only this conversation token: {right_token}")

    _, left_context, _ = api_request(
        "GET",
        f"/api/conversations/{left['id']}/context?include_messages=true",
        expected=200,
    )
    _, right_context, _ = api_request(
        "GET",
        f"/api/conversations/{right['id']}/context?include_messages=true",
        expected=200,
    )

    left_blob = json.dumps(left_context, ensure_ascii=False)
    right_blob = json.dumps(right_context, ensure_ascii=False)
    assert left_token in left_blob
    assert right_token not in left_blob, left_context
    assert right_token in right_blob
    assert left_token not in right_blob, right_context

    _, task, _ = api_request(
        "POST",
        f"/api/conversations/{left['id']}/tasks",
        {
            "goal": "Answer using this conversation context only.",
            "acceptance": {"must_include": left_token, "must_not_include": right_token},
        },
        expected={200, 201, 202},
    )
    task_id = task.get("id") or task.get("task_id")
    assert task_id
    _, task_context, _ = api_request("GET", f"/api/tasks/{task_id}/context", expected=200)
    task_blob = json.dumps(task_context, ensure_ascii=False)
    assert left_token in task_blob
    assert right_token not in task_blob, task_context
