from pathlib import Path

import pytest

from services.api.app.artifacts.patch_service import apply_patch_request
from services.api.app.artifacts.repository import create_artifact, list_artifact_versions
from services.api.app.artifacts.review_repository import create_review_decision
from services.api.app.conversations.repository import create_conversation
from services.api.app.shared.errors import ValidationError


def _store_dir(test_run_id):
    return Path("var") / "test-artifacts" / test_run_id


def _source_and_patch(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-review-policy"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = create_conversation(
        title=f"{unique_id} review policy",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )
    source = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="source_file",
        title="policy.txt",
        mime_type="text/plain",
        content="hello\n",
        test_run_id=test_run_id,
    )
    patch = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="patch",
        title="policy.patch",
        mime_type="text/x-diff",
        content="--- policy.txt\n+++ policy.txt\n@@\n-hello\n+hello policy\n",
        target_artifact_id=str(source["id"]),
        base_version_id=str(source["current_version_id"]),
        base_checksum=str(source["checksum"]),
        test_run_id=test_run_id,
    )
    return test_run_id, source, patch


def test_review_gate_requires_approval_before_apply(monkeypatch, unique_id):
    test_run_id, source, patch = _source_and_patch(monkeypatch, unique_id)

    result = apply_patch_request(str(patch["id"]), {"target_artifact_id": source["id"]}, test_run_id=test_run_id)
    versions = list_artifact_versions(str(source["id"]), test_run_id=test_run_id)

    assert result["status"] == "review_required"
    assert result["review_request_id"]
    assert len(versions) == 1


def test_review_gate_decision_is_single_use_state_transition(monkeypatch, unique_id):
    test_run_id, source, patch = _source_and_patch(monkeypatch, unique_id)
    result = apply_patch_request(str(patch["id"]), {"target_artifact_id": source["id"]}, test_run_id=test_run_id)
    create_review_decision(
        request_id=str(result["review_request_id"]),
        decision="approved",
        decided_by="contract-test",
        comment=None,
        test_run_id=test_run_id,
    )

    with pytest.raises(ValidationError) as exc_info:
        create_review_decision(
            request_id=str(result["review_request_id"]),
            decision="rejected",
            decided_by="contract-test",
            comment=None,
            test_run_id=test_run_id,
        )

    assert exc_info.value.code == "review_request_not_pending"
