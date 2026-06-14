from tests.support import create_conversation, item_list, post_message, task_from_message, wait_artifacts, wait_task


def test_a18_document_range_processing_only_changes_selected_range(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} document range")
    original = "\n".join(
        [
            "# Release Notes",
            "",
            "## Background",
            "Keep this background unchanged.",
            "",
            "## Scope",
            "Replace only this scope paragraph.",
            "",
            "## Risks",
            "Keep this risk paragraph unchanged.",
            "",
        ]
    )
    _, document, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation["id"],
            "type": "document",
            "title": "range-release-notes.md",
            "mime_type": "text/markdown",
            "content": original,
        },
        expected={200, 201},
    )
    base_version = document.get("current_version_id") or document.get("version")
    message = post_message(
        api_request,
        conversation["id"],
        "Rewrite only the Scope section. Do not alter Background or Risks.",
        references=[
            {
                "type": "artifact_range",
                "artifact_id": document["id"],
                "base_version_id": base_version,
                "range": {"kind": "markdown_heading", "heading": "Scope"},
            }
        ],
    )
    wait_task(api_request, task_from_message(message), terminal=("succeeded", "failed"), timeout=180)

    patches = wait_artifacts(api_request, conversation["id"], artifact_type="document_patch", minimum=1)
    patch = patches[0]
    assert patch.get("target_artifact_id") == document["id"] or patch.get("content", {}).get("target_artifact_id") == document["id"]
    content = patch.get("content", {})
    ranges = content.get("affected_ranges") or patch.get("affected_ranges") or []
    assert ranges, patch
    assert any(item.get("heading") == "Scope" or item.get("selector") == "## Scope" for item in ranges), patch
    patch_text = str(content)
    assert "Background" not in patch_text or "Keep this background unchanged." not in patch_text
    assert "Risks" not in patch_text or "Keep this risk paragraph unchanged." not in patch_text

    _, latest_document, _ = api_request("GET", f"/api/artifacts/{document['id']}", expected=200)
    latest_version = latest_document.get("current_version_id") or latest_document.get("version")
    assert latest_version == base_version, "Document range processing must create a patch before mutating source"

    _, messages_payload, _ = api_request("GET", f"/api/conversations/{conversation['id']}/messages", expected=200)
    messages = item_list(messages_payload)
    assert any(
        msg.get("message_type") in {"artifact_card", "document_patch_card", "card"}
        and (
            msg.get("content", {}).get("artifact_id") == patch["id"]
            or msg.get("content", {}).get("patch_artifact_id") == patch["id"]
        )
        for msg in messages
    ), messages
