from tests.support import create_conversation, item_list


def _create_artifact(api_request, conversation_id, artifact_type, title, content, mime_type="application/json", extra=None):
    body = {
        "conversation_id": conversation_id,
        "type": artifact_type,
        "title": title,
        "mime_type": mime_type,
        "content": content,
    }
    if extra:
        body.update(extra)
    _, artifact, _ = api_request("POST", "/api/artifacts", body, expected={200, 201})
    assert artifact.get("id"), artifact
    return artifact


def test_a15_code_file_image_web_diff_and_deployment_cards(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} rich cards")
    source = _create_artifact(
        api_request,
        conversation["id"],
        "source_code",
        "card-source",
        {"files": {"app.py": "print('before')\n"}},
        mime_type="application/vnd.agenthub.source+json",
    )
    file_artifact = _create_artifact(
        api_request,
        conversation["id"],
        "file",
        "requirements.txt",
        "fastapi\nuvicorn\n",
        mime_type="text/plain",
    )
    image_artifact = _create_artifact(
        api_request,
        conversation["id"],
        "image",
        "one-pixel.png",
        {"data_url": "data:image/png;base64,iVBORw0KGgo="},
        mime_type="image/png",
    )
    diff_artifact = _create_artifact(
        api_request,
        conversation["id"],
        "diff",
        "app.py.patch",
        {
            "target_artifact_id": source["id"],
            "base_version_id": source.get("current_version_id") or source.get("version"),
            "patch": "--- a/app.py\n+++ b/app.py\n@@\n-print('before')\n+print('after')\n",
        },
        mime_type="text/x-diff",
    )
    _, release, _ = api_request(
        "POST",
        "/api/deployments",
        {
            "conversation_id": conversation["id"],
            "artifact_id": source["id"],
            "provider": "default",
            "trigger": {"type": "acceptance_card_schema"},
        },
        expected={200, 201, 202},
    )
    release_id = release.get("id") or release.get("deployment_id")
    assert release_id, release

    card_inputs = [
        {
            "message_type": "code_block",
            "content": {"card_type": "code_block", "language": "python", "code": "print('card')\n"},
        },
        {
            "message_type": "file_card",
            "content": {
                "card_type": "file_card",
                "artifact_id": file_artifact["id"],
                "filename": "requirements.txt",
                "mime_type": "text/plain",
            },
        },
        {
            "message_type": "image_card",
            "content": {
                "card_type": "image_card",
                "artifact_id": image_artifact["id"],
                "alt": "acceptance pixel",
            },
        },
        {
            "message_type": "webpage_card",
            "content": {
                "card_type": "webpage_card",
                "url": "https://example.com/",
                "title": "Example Domain",
            },
        },
        {
            "message_type": "diff_card",
            "content": {
                "card_type": "diff_card",
                "artifact_id": diff_artifact["id"],
                "target_artifact_id": source["id"],
            },
        },
        {
            "message_type": "deployment_card",
            "content": {
                "card_type": "deployment_card",
                "release_id": release_id,
                "artifact_id": source["id"],
            },
        },
    ]
    created_ids = []
    for body in card_inputs:
        _, msg, _ = api_request(
            "POST",
            f"/api/conversations/{conversation['id']}/messages",
            body,
            expected={200, 201},
        )
        created_ids.append(msg["id"])

    _, payload, _ = api_request("GET", f"/api/conversations/{conversation['id']}/messages", expected=200)
    messages = [msg for msg in item_list(payload) if msg.get("id") in created_ids]
    by_type = {msg.get("message_type"): msg for msg in messages}
    for message_type in [item["message_type"] for item in card_inputs]:
        assert message_type in by_type, f"Missing {message_type}; messages={messages}"

    for artifact_id in [file_artifact["id"], image_artifact["id"], diff_artifact["id"]]:
        _, artifact, _ = api_request("GET", f"/api/artifacts/{artifact_id}", expected=200)
        assert artifact["id"] == artifact_id
    _, deployment, _ = api_request("GET", f"/api/deployments/{release_id}", expected=200)
    assert (deployment.get("id") or deployment.get("deployment_id")) == release_id
