from tests.support import create_conversation


def test_a10_apply_patch_permission(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} patch permission")
    _, source, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation["id"],
            "type": "source_file",
            "title": "hello.txt",
            "mime_type": "text/plain",
            "content": "hello\n",
        },
        expected={200, 201},
    )
    base_version = source.get("current_version_id") or source.get("version")
    _, initial_versions, _ = api_request("GET", f"/api/artifacts/{source['id']}/versions", expected=200)
    initial_version_count = len(initial_versions.get("items", []))
    _, patch, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation["id"],
            "type": "patch",
            "title": "hello update.patch",
            "target_artifact_id": source["id"],
            "base_version_id": base_version,
            "mime_type": "text/x-diff",
            "content": "--- hello.txt\n+++ hello.txt\n@@\n-hello\n+hello world\n",
        },
        expected={200, 201},
    )

    status, first_apply, _ = api_request(
        "POST",
        f"/api/artifacts/{patch['id']}/apply-patch",
        {"target_artifact_id": source["id"]},
        expected={403, 409, 202},
    )
    assert first_apply.get("error_code") == "review_required" or first_apply.get("review_request_id")
    review_request_id = first_apply.get("review_request_id")
    assert review_request_id, f"Patch apply must create or return review request: {first_apply}"

    _, gated_versions, _ = api_request("GET", f"/api/artifacts/{source['id']}/versions", expected=200)
    assert len(gated_versions.get("items", [])) == initial_version_count
    _, current_source, _ = api_request("GET", f"/api/artifacts/{source['id']}", expected=200)
    assert (current_source.get("current_version_id") or current_source.get("version")) == base_version

    _, review_requests, _ = api_request("GET", "/api/review-requests?status=pending", expected=200)
    review_request = next(item for item in review_requests.get("items", []) if item["id"] == review_request_id)
    assert review_request["action_type"] == "apply_patch"
    assert review_request["status"] == "pending"
    assert review_request["artifact_id"] == patch["id"]
    assert review_request["payload"]["target_artifact_id"] == source["id"]

    api_request(
        "POST",
        f"/api/review-requests/{review_request_id}/decision",
        {"decision": "approved", "comment": "Acceptance test approval"},
        expected={200, 201, 202},
    )

    _, applied, _ = api_request(
        "POST",
        f"/api/artifacts/{patch['id']}/apply-patch",
        {"target_artifact_id": source["id"], "review_request_id": review_request_id},
        expected={200, 201, 202},
    )
    assert applied.get("status") in {"applied", "succeeded"}
    assert applied.get("new_version_id")
    assert applied["new_version_id"] != base_version
    assert applied.get("audit_log_id")
