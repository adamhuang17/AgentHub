from tests.support import create_conversation, item_list


def _create_source(api_request, conversation_id, title, content):
    _, artifact, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation_id,
            "type": "source_file",
            "title": title,
            "mime_type": "text/x-python",
            "content": content,
        },
        expected={200, 201},
    )
    return artifact


def test_a9_diff_artifact_preview_api_and_message_card(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} diff preview")
    base_content = "def add(a, b):\n    return a + b\n"
    target_content = (
        "def add(a, b):\n"
        "    if not isinstance(a, (int, float)):\n"
        "        raise TypeError('a must be numeric')\n"
        "    return a + b\n"
    )
    base = _create_source(api_request, conversation["id"], "calculator.py", base_content)
    target = _create_source(api_request, conversation["id"], "calculator.py", target_content)
    base_version_id = base["current_version_id"]
    target_version_id = target["current_version_id"]

    _, diff, _ = api_request(
        "POST",
        "/api/artifacts/diff",
        {
            "base_artifact_id": base["id"],
            "base_version_id": base_version_id,
            "target_artifact_id": target["id"],
            "target_version_id": target_version_id,
            "path": "calculator.py",
            "type": "diff_preview",
        },
        expected={200, 201},
    )

    assert diff["diff_artifact_id"]
    assert diff["type"] == "diff_preview"
    assert diff["base_artifact_id"] == base["id"]
    assert diff["base_version_id"] == base_version_id
    assert diff["target_artifact_id"] == target["id"]
    assert diff["target_version_id"] == target_version_id
    assert diff["additions"] == 2
    assert diff["deletions"] == 0
    assert diff["checksum"].startswith("sha256:")
    assert diff["files"][0]["path"] == "calculator.py"
    assert diff["hunks"][0]["file_path"] == "calculator.py"

    _, diff_read, _ = api_request("GET", f"/api/artifacts/{diff['diff_artifact_id']}/diff", expected=200)
    _, diff_content, _ = api_request("GET", f"/api/artifacts/{diff['diff_artifact_id']}/content", expected=200)
    assert diff_read["checksum"] == diff["checksum"]
    assert "+    if not isinstance(a, (int, float)):" in diff_read["files"][0]["unified_diff"]
    assert "unified_diff" in diff_content["content"]

    _, message, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "Please review the diff preview."},
            "references": [{"type": "artifact", "artifact_id": diff["diff_artifact_id"]}],
        },
        expected={200, 201},
    )
    assert message["content"] == {"text": "Please review the diff preview."}
    assert "TypeError" not in str(message["content"])
    assert message["diff_card"]["diff_artifact_id"] == diff["diff_artifact_id"]
    assert message["diff_card"]["additions"] == 2

    _, messages_payload, _ = api_request("GET", f"/api/conversations/{conversation['id']}/messages", expected=200)
    stored_message = next(item for item in item_list(messages_payload) if item["id"] == message["id"])
    assert stored_message["diff_card"]["diff_artifact_id"] == diff["diff_artifact_id"]
    assert "TypeError" not in str(stored_message["content"])

    _, base_after, _ = api_request("GET", f"/api/artifacts/{base['id']}", expected=200)
    _, base_content_after, _ = api_request("GET", f"/api/artifacts/{base['id']}/content", expected=200)
    assert base_after["current_version_id"] == base_version_id
    assert base_content_after["content"] == base_content

    _, artifacts_payload, _ = api_request("GET", f"/api/artifacts?conversation_id={conversation['id']}", expected=200)
    artifact_types = {artifact["type"] for artifact in item_list(artifacts_payload)}
    assert "deployment" not in artifact_types
    assert "deployment_release" not in artifact_types
