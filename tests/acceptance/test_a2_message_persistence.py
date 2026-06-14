from tests.support import create_conversation, item_list, post_message


def test_a2_message_persistence(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} message persistence")
    message = post_message(api_request, conversation["id"], f"{unique_id} persistent message")

    _, payload, _ = api_request("GET", f"/api/conversations/{conversation['id']}/messages", expected=200)
    messages = item_list(payload)
    stored = next((m for m in messages if m["id"] == message["id"]), None)
    assert stored is not None
    assert stored["message_type"] == "text"
    assert stored["content"]["text"] == f"{unique_id} persistent message"
    assert stored.get("created_at")
