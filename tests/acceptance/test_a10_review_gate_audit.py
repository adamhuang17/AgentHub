import os

from services.api.app.permissions import audit_repository
from tests.support import create_conversation


def test_a10_review_gate_audit_and_duplicate_apply(api_request, unique_id):
    test_run_id = os.getenv("AGENTHUB_TEST_RUN_ID", "local")
    conversation = create_conversation(api_request, f"{unique_id} review audit")
    _, source, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation["id"],
            "type": "source_file",
            "title": "audit.txt",
            "mime_type": "text/plain",
            "content": "hello\n",
        },
        expected={200, 201},
    )
    base_version = source["current_version_id"]
    _, patch, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation["id"],
            "type": "patch",
            "title": "audit.patch",
            "target_artifact_id": source["id"],
            "base_version_id": base_version,
            "base_checksum": source["checksum"],
            "mime_type": "text/x-diff",
            "content": "--- audit.txt\n+++ audit.txt\n@@\n-hello\n+hello audit\n",
        },
        expected={200, 201},
    )

    _, first_apply, _ = api_request(
        "POST",
        f"/api/artifacts/{patch['id']}/apply-patch",
        {"target_artifact_id": source["id"]},
        expected=202,
    )
    review_request_id = first_apply["review_request_id"]
    review_logs = audit_repository.list_audit_logs(
        test_run_id=test_run_id,
        action_type="review_request.created",
        target_type="review_request",
        target_id=review_request_id,
    )
    review_required_logs = audit_repository.list_audit_logs(
        test_run_id=test_run_id,
        action_type="patch_application.review_required",
        target_type="patch_application",
        target_id=first_apply["id"],
    )
    assert review_logs and review_logs[0]["payload_hash"].startswith("sha256:")
    assert review_required_logs and review_required_logs[0]["id"] == first_apply["audit_log_id"]

    _, decision, _ = api_request(
        "POST",
        f"/api/review-requests/{review_request_id}/decision",
        {"decision": "approved", "decided_by": "acceptance-test", "comment": "Approve audit path."},
        expected={200, 201, 202},
    )
    decision_logs = audit_repository.list_audit_logs(
        test_run_id=test_run_id,
        action_type="review_decision.approved",
        target_type="review_decision",
        target_id=decision["id"],
    )
    assert decision_logs and decision_logs[0]["id"] == decision["audit_log_id"]

    _, applied, _ = api_request(
        "POST",
        f"/api/artifacts/{patch['id']}/apply-patch",
        {"target_artifact_id": source["id"], "review_request_id": review_request_id},
        expected=200,
    )
    _, duplicate, _ = api_request(
        "POST",
        f"/api/artifacts/{patch['id']}/apply-patch",
        {"target_artifact_id": source["id"], "review_request_id": review_request_id},
        expected=200,
    )
    _, versions, _ = api_request("GET", f"/api/artifacts/{source['id']}/versions", expected=200)
    applied_logs = audit_repository.list_audit_logs(
        test_run_id=test_run_id,
        action_type="patch_application.applied",
        target_type="patch_application",
        target_id=applied["id"],
    )

    assert applied["status"] == "applied"
    assert applied["audit_log_id"]
    assert duplicate["id"] == applied["id"]
    assert duplicate["new_version_id"] == applied["new_version_id"]
    assert duplicate["idempotent"] is True
    assert len(versions["items"]) == 2
    assert applied_logs and applied_logs[0]["id"] == applied["audit_log_id"]
