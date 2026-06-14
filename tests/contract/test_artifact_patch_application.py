from pathlib import Path

from services.api.app.artifacts.patch_service import apply_patch_request
from services.api.app.artifacts.repository import (
    append_artifact_version,
    create_artifact,
    list_artifact_versions,
    read_artifact_content,
)
from services.api.app.artifacts.review_repository import create_review_decision, list_review_requests
from services.api.app.conversations.repository import create_conversation
from services.api.app.permissions import audit_repository


def _store_dir(test_run_id):
    return Path("var") / "test-artifacts" / test_run_id


def _source_and_patch(monkeypatch, unique_id, *, source_text="hello\n", patch_text=None, base_checksum=None):
    test_run_id = f"{unique_id}-patch-apply"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = create_conversation(
        title=f"{unique_id} patch apply",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )
    source = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="source_file",
        title="hello.txt",
        mime_type="text/plain",
        content=source_text,
        test_run_id=test_run_id,
    )
    patch = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="patch",
        title="hello.patch",
        mime_type="text/x-diff",
        content=patch_text or "--- hello.txt\n+++ hello.txt\n@@\n-hello\n+hello world\n",
        target_artifact_id=str(source["id"]),
        base_version_id=str(source["current_version_id"]),
        base_checksum=base_checksum if base_checksum is not None else str(source["checksum"]),
        test_run_id=test_run_id,
    )
    return test_run_id, source, patch


def _approve_patch(test_run_id, source, patch):
    first = apply_patch_request(str(patch["id"]), {"target_artifact_id": source["id"]}, test_run_id=test_run_id)
    decision = create_review_decision(
        request_id=str(first["review_request_id"]),
        decision="approved",
        decided_by="contract-test",
        comment="approved",
        test_run_id=test_run_id,
    )
    return first, decision


def test_apply_patch_first_call_creates_review_request_without_new_version(monkeypatch, unique_id):
    test_run_id, source, patch = _source_and_patch(monkeypatch, unique_id)

    result = apply_patch_request(str(patch["id"]), {"target_artifact_id": source["id"]}, test_run_id=test_run_id)
    requests = list_review_requests(test_run_id=test_run_id, status="pending")
    versions = list_artifact_versions(str(source["id"]), test_run_id=test_run_id)

    assert result["status"] == "review_required"
    assert result["error_code"] == "review_required"
    assert result["review_request_id"]
    assert requests[0]["id"] == result["review_request_id"]
    assert requests[0]["action_type"] == "apply_patch"
    assert requests[0]["status"] == "pending"
    assert requests[0]["artifact_id"] == patch["id"]
    assert requests[0]["payload"]["target_artifact_id"] == source["id"]
    assert set(["id", "conversation_id", "artifact_id", "action_type", "status", "payload_json", "created_at"]).issubset(
        requests[0]
    )
    review_logs = audit_repository.list_audit_logs(
        test_run_id=test_run_id,
        action_type="review_request.created",
        target_type="review_request",
        target_id=str(result["review_request_id"]),
    )
    application_logs = audit_repository.list_audit_logs(
        test_run_id=test_run_id,
        action_type="patch_application.review_required",
        target_type="patch_application",
        target_id=str(result["id"]),
    )
    assert review_logs and review_logs[0]["payload_hash"].startswith("sha256:")
    assert application_logs and application_logs[0]["id"] == result["audit_log_id"]
    assert len(versions) == 1


def test_rejected_patch_does_not_create_artifact_version(monkeypatch, unique_id):
    test_run_id, source, patch = _source_and_patch(monkeypatch, unique_id)
    first = apply_patch_request(str(patch["id"]), {"target_artifact_id": source["id"]}, test_run_id=test_run_id)

    decision = create_review_decision(
        request_id=str(first["review_request_id"]),
        decision="rejected",
        decided_by="contract-test",
        comment="Nope.",
        test_run_id=test_run_id,
    )
    result = apply_patch_request(
        str(patch["id"]),
        {"target_artifact_id": source["id"], "review_request_id": first["review_request_id"]},
        test_run_id=test_run_id,
    )
    versions = list_artifact_versions(str(source["id"]), test_run_id=test_run_id)

    assert set(["id", "request_id", "decision", "decided_by", "comment", "created_at"]).issubset(decision)
    assert decision["decision"] == "rejected"
    assert result["status"] == "rejected"
    assert result["error_code"] == "review_rejected"
    assert decision["audit_log_id"]
    assert result["audit_log_id"]
    assert audit_repository.list_audit_logs(
        test_run_id=test_run_id,
        action_type="review_decision.rejected",
        target_type="review_decision",
        target_id=str(decision["id"]),
    )
    assert audit_repository.list_audit_logs(
        test_run_id=test_run_id,
        action_type="patch_application.rejected",
        target_type="patch_application",
        target_id=str(result["id"]),
    )
    assert len(versions) == 1


def test_approved_patch_creates_new_artifact_version_with_parent(monkeypatch, unique_id):
    test_run_id, source, patch = _source_and_patch(monkeypatch, unique_id)
    base_version_id = str(source["current_version_id"])
    first, decision = _approve_patch(test_run_id, source, patch)

    result = apply_patch_request(
        str(patch["id"]),
        {"target_artifact_id": source["id"], "review_request_id": first["review_request_id"]},
        test_run_id=test_run_id,
    )
    versions = list_artifact_versions(str(source["id"]), test_run_id=test_run_id)
    content = read_artifact_content(str(source["id"]), test_run_id=test_run_id)

    assert result["status"] == "applied"
    assert result["result_version_id"] == result["new_version_id"]
    assert result["result_version_id"] != base_version_id
    assert versions[-1]["id"] == result["result_version_id"]
    assert versions[-1]["parent_version_id"] == base_version_id
    assert content["content"] == "hello world\n"
    assert decision["audit_log_id"]
    assert result["audit_log_id"]
    assert audit_repository.list_audit_logs(
        test_run_id=test_run_id,
        action_type="review_decision.approved",
        target_type="review_decision",
        target_id=str(decision["id"]),
    )
    assert audit_repository.list_audit_logs(
        test_run_id=test_run_id,
        action_type="patch_application.applied",
        target_type="patch_application",
        target_id=str(result["id"]),
    )


def test_duplicate_approved_apply_returns_existing_application_without_second_version(monkeypatch, unique_id):
    test_run_id, source, patch = _source_and_patch(monkeypatch, unique_id)
    first, _ = _approve_patch(test_run_id, source, patch)
    applied = apply_patch_request(
        str(patch["id"]),
        {"target_artifact_id": source["id"], "review_request_id": first["review_request_id"]},
        test_run_id=test_run_id,
    )

    duplicate = apply_patch_request(
        str(patch["id"]),
        {"target_artifact_id": source["id"], "review_request_id": first["review_request_id"]},
        test_run_id=test_run_id,
    )
    versions = list_artifact_versions(str(source["id"]), test_run_id=test_run_id)

    assert duplicate["status"] == "applied"
    assert duplicate["id"] == applied["id"]
    assert duplicate["new_version_id"] == applied["new_version_id"]
    assert duplicate["idempotent"] is True
    assert len(versions) == 2


def test_stale_base_fails_without_new_version(monkeypatch, unique_id):
    test_run_id, source, patch = _source_and_patch(monkeypatch, unique_id)
    first, _ = _approve_patch(test_run_id, source, patch)
    append_artifact_version(
        str(source["id"]),
        content="hello from another version\n",
        parent_version_id=str(source["current_version_id"]),
        test_run_id=test_run_id,
    )

    result = apply_patch_request(
        str(patch["id"]),
        {"target_artifact_id": source["id"], "review_request_id": first["review_request_id"]},
        test_run_id=test_run_id,
    )
    versions = list_artifact_versions(str(source["id"]), test_run_id=test_run_id)
    content = read_artifact_content(str(source["id"]), test_run_id=test_run_id)

    assert result["status"] == "failed"
    assert result["error_code"] == "artifact_apply_stale_base"
    assert result["audit_log_id"]
    assert len(versions) == 2
    assert content["content"] == "hello from another version\n"


def test_checksum_mismatch_fails_without_new_version(monkeypatch, unique_id):
    test_run_id, source, patch = _source_and_patch(
        monkeypatch,
        unique_id,
        base_checksum="sha256:not-the-stored-checksum",
    )
    first, _ = _approve_patch(test_run_id, source, patch)

    result = apply_patch_request(
        str(patch["id"]),
        {"target_artifact_id": source["id"], "review_request_id": first["review_request_id"]},
        test_run_id=test_run_id,
    )
    versions = list_artifact_versions(str(source["id"]), test_run_id=test_run_id)
    content = read_artifact_content(str(source["id"]), test_run_id=test_run_id)

    assert result["status"] == "failed"
    assert result["error_code"] == "artifact_apply_checksum_mismatch"
    assert result["audit_log_id"]
    assert len(versions) == 1
    assert content["content"] == "hello\n"


def test_conflicting_patch_does_not_overwrite_old_content(monkeypatch, unique_id):
    test_run_id, source, patch = _source_and_patch(
        monkeypatch,
        unique_id,
        patch_text="--- hello.txt\n+++ hello.txt\n@@\n-goodbye\n+hello world\n",
    )
    first, _ = _approve_patch(test_run_id, source, patch)

    result = apply_patch_request(
        str(patch["id"]),
        {"target_artifact_id": source["id"], "review_request_id": first["review_request_id"]},
        test_run_id=test_run_id,
    )
    versions = list_artifact_versions(str(source["id"]), test_run_id=test_run_id)
    content = read_artifact_content(str(source["id"]), test_run_id=test_run_id)

    assert result["status"] == "conflict"
    assert result["error_code"] == "artifact_apply_conflict"
    assert result["audit_log_id"]
    assert audit_repository.list_audit_logs(
        test_run_id=test_run_id,
        action_type="patch_application.conflict",
        target_type="patch_application",
        target_id=str(result["id"]),
    )
    assert len(versions) == 1
    assert content["content"] == "hello\n"


def test_applied_patch_transaction_rolls_back_version_if_audit_fails(monkeypatch, unique_id):
    test_run_id, source, patch = _source_and_patch(monkeypatch, unique_id)
    first, _ = _approve_patch(test_run_id, source, patch)
    original_record = audit_repository.record_audit_log

    def fail_applied_audit(connection, **kwargs):
        if kwargs.get("action_type") == "patch_application.applied":
            raise RuntimeError("forced audit failure")
        return original_record(connection, **kwargs)

    monkeypatch.setattr(audit_repository, "record_audit_log", fail_applied_audit)

    try:
        apply_patch_request(
            str(patch["id"]),
            {"target_artifact_id": source["id"], "review_request_id": first["review_request_id"]},
            test_run_id=test_run_id,
        )
    except RuntimeError as exc:
        assert "forced audit failure" in str(exc)
    else:
        raise AssertionError("forced audit failure must propagate")

    versions = list_artifact_versions(str(source["id"]), test_run_id=test_run_id)
    content = read_artifact_content(str(source["id"]), test_run_id=test_run_id)
    assert len(versions) == 1
    assert content["content"] == "hello\n"
