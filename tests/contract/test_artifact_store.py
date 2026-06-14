from pathlib import Path

import pytest

from services.api.app.artifacts.repository import (
    create_artifact,
    get_artifact,
    list_artifact_versions,
    read_artifact_content,
)
from services.api.app.conversations.repository import create_conversation, create_message, list_messages
from services.api.app.shared.errors import ValidationError


def _store_dir(test_run_id):
    return Path("var") / "test-artifacts" / test_run_id


def test_artifact_store_persists_content_with_stable_checksum(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-artifact-store"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = create_conversation(
        title=f"{unique_id} artifact store",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )
    content = f"# Artifact Store\n\nStable payload for {unique_id}.\n"

    artifact = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="document",
        title="Artifact Store Contract",
        mime_type="text/markdown",
        content=content,
        test_run_id=test_run_id,
    )
    versions = list_artifact_versions(str(artifact["id"]), test_run_id=test_run_id)
    first_read = read_artifact_content(str(artifact["id"]), test_run_id=test_run_id)
    second_read = read_artifact_content(str(artifact["id"]), test_run_id=test_run_id)

    assert artifact["storage_key"]
    assert artifact["checksum"] == versions[0]["checksum"]
    assert versions[0]["version"] == 1
    assert versions[0]["parent_version_id"] is None
    assert first_read["content"] == content
    assert first_read["checksum"] == second_read["checksum"]
    assert get_artifact(str(artifact["id"]), test_run_id=test_run_id)["checksum"] == first_read["checksum"]


def test_artifact_store_rejects_secret_like_content(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-artifact-secret"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = create_conversation(
        title=f"{unique_id} artifact secret",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )

    with pytest.raises(ValidationError) as exc_info:
        create_artifact(
            conversation_id=str(conversation["id"]),
            artifact_type="document",
            title="Secret Artifact",
            mime_type="text/plain",
            content="token = sk-proj-this-value-must-not-enter-artifacts",
            test_run_id=test_run_id,
        )

    assert exc_info.value.code == "artifact_secret_forbidden"


def test_message_reference_does_not_store_artifact_body(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-artifact-reference"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = create_conversation(
        title=f"{unique_id} artifact reference",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )
    content = f"Large-ish artifact body that belongs in the store only: {unique_id}"
    artifact = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="document",
        title="Reference Artifact",
        mime_type="text/plain",
        content=content,
        test_run_id=test_run_id,
    )
    message = create_message(
        conversation_id=str(conversation["id"]),
        message_type="text",
        content={"text": "See attached artifact reference."},
        mentions=[],
        references=[{"type": "artifact", "artifact_id": artifact["id"]}],
        reply_to_id=None,
        test_run_id=test_run_id,
    )
    stored = next(item for item in list_messages(str(conversation["id"]), test_run_id=test_run_id) if item["id"] == message["id"])

    assert stored["content"] == {"text": "See attached artifact reference."}
    assert content not in str(stored["content"])
    assert stored["references"] == [{"type": "artifact", "artifact_id": artifact["id"]}]
    assert stored["artifact_card"]["artifact_id"] == artifact["id"]
