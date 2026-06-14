from tests.support import create_conversation
from tests.schema_assertions import assert_keys


def test_artifact_protocol(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} artifact protocol")
    _, artifact, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation["id"],
            "type": "document",
            "title": "Contract Document",
            "mime_type": "text/markdown",
            "content": "# Contract\n",
        },
        expected={200, 201},
    )
    assert_keys(artifact, ["id", "conversation_id", "type", "title", "status"])
    assert artifact["conversation_id"] == conversation["id"]
    assert artifact["type"] == "document"
    assert artifact.get("current_version_id") or artifact.get("version")
