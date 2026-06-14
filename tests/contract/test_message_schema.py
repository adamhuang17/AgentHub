from tests.support import create_conversation, post_message
from tests.schema_assertions import assert_keys, assert_non_empty_string


def test_message_schema(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} message schema")
    message = post_message(api_request, conversation["id"], "schema check")
    assert_keys(
        message,
        [
            "id",
            "conversation_id",
            "message_type",
            "content",
            "mentions",
            "references",
            "reply_to_id",
            "created_at",
        ],
    )
    assert_non_empty_string(message["id"], "message.id")
    assert message["conversation_id"] == conversation["id"]
    assert message["message_type"] == "text"
    assert message["content"]["text"] == "schema check"
    assert message["mentions"] == []
    assert message["references"] == []
    assert message["reply_to_id"] is None


def test_message_relation_fields_round_trip(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} message relation schema")
    parent = post_message(api_request, conversation["id"], "parent message")
    mentions = [{"agent_id": "agent-codex-profile", "display": "Codex Profile"}]
    references = [{"type": "message", "message_id": parent["id"]}]

    _, message, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "reply with metadata"},
            "mentions": mentions,
            "references": references,
            "reply_to_id": parent["id"],
        },
        expected={200, 201},
    )

    assert message["mentions"] == mentions
    assert message["references"] == references
    assert message["reply_to_id"] == parent["id"]

    _, payload, _ = api_request("GET", f"/api/conversations/{conversation['id']}/messages", expected=200)
    stored = next(item for item in payload["items"] if item["id"] == message["id"])
    assert stored["mentions"] == mentions
    assert stored["references"] == references
    assert stored["reply_to_id"] == parent["id"]
