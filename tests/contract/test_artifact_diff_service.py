from pathlib import Path

import pytest

from services.api.app.artifacts.diff_service import create_diff_artifact_from_request
from services.api.app.artifacts.repository import create_artifact, list_artifacts, read_artifact_content
from services.api.app.conversations.repository import create_conversation, create_message, list_messages
from services.api.app.shared.errors import ValidationError


def _store_dir(test_run_id):
    return Path("var") / "test-artifacts" / test_run_id


def _conversation(test_run_id, unique_id):
    return create_conversation(
        title=f"{unique_id} diff service",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )


def _source_artifact(conversation_id, test_run_id, title, content, mime_type="text/plain"):
    return create_artifact(
        conversation_id=conversation_id,
        artifact_type="source_file",
        title=title,
        mime_type=mime_type,
        content=content,
        test_run_id=test_run_id,
    )


def test_diff_service_creates_read_only_diff_artifact(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-diff-service"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = _conversation(test_run_id, unique_id)
    base = _source_artifact(str(conversation["id"]), test_run_id, "math.py", "def add(a, b):\n    return a + b\n")
    target = _source_artifact(
        str(conversation["id"]),
        test_run_id,
        "math.py",
        "def add(a, b):\n    if not isinstance(a, (int, float)):\n        raise TypeError('a')\n    return a + b\n",
    )

    diff = create_diff_artifact_from_request(
        {
            "base_artifact_id": base["id"],
            "base_version_id": base["current_version_id"],
            "target_artifact_id": target["id"],
            "target_version_id": target["current_version_id"],
            "path": "math.py",
            "type": "source_diff",
        },
        test_run_id=test_run_id,
    )
    base_after = read_artifact_content(str(base["id"]), test_run_id=test_run_id)
    diff_content = read_artifact_content(str(diff["diff_artifact_id"]), test_run_id=test_run_id)

    assert diff["type"] == "source_diff"
    assert diff["base_artifact_id"] == base["id"]
    assert diff["base_version_id"] == base["current_version_id"]
    assert diff["target_artifact_id"] == target["id"]
    assert diff["target_version_id"] == target["current_version_id"]
    assert diff["additions"] == 2
    assert diff["deletions"] == 0
    assert diff["checksum"].startswith("sha256:")
    assert diff["files"][0]["path"] == "math.py"
    assert diff["hunks"][0]["file_path"] == "math.py"
    assert "+    if not isinstance(a, (int, float)):" in diff["files"][0]["unified_diff"]
    assert base_after["content"] == "def add(a, b):\n    return a + b\n"
    assert diff_content["artifact_id"] == diff["diff_artifact_id"]
    assert "unified_diff" in diff_content["content"]


def test_diff_service_message_reference_returns_diff_card(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-diff-card"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = _conversation(test_run_id, unique_id)
    base = _source_artifact(str(conversation["id"]), test_run_id, "note.txt", "hello\n")
    target = _source_artifact(str(conversation["id"]), test_run_id, "note.txt", "hello world\n")
    diff = create_diff_artifact_from_request(
        {
            "base_artifact_id": base["id"],
            "base_version_id": base["current_version_id"],
            "target_artifact_id": target["id"],
            "target_version_id": target["current_version_id"],
        },
        test_run_id=test_run_id,
    )

    message = create_message(
        conversation_id=str(conversation["id"]),
        message_type="text",
        content={"text": "Review the diff card only."},
        mentions=[],
        references=[{"type": "artifact", "artifact_id": diff["diff_artifact_id"]}],
        reply_to_id=None,
        test_run_id=test_run_id,
    )
    stored = next(item for item in list_messages(str(conversation["id"]), test_run_id=test_run_id) if item["id"] == message["id"])

    assert stored["content"] == {"text": "Review the diff card only."}
    assert "hello world" not in str(stored["content"])
    assert stored["diff_card"]["card_type"] == "diff_card"
    assert stored["diff_card"]["diff_artifact_id"] == diff["diff_artifact_id"]
    assert stored["diff_card"]["additions"] == 1
    assert "artifact_card" not in stored


def test_diff_service_missing_target_does_not_create_artifact(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-diff-missing"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = _conversation(test_run_id, unique_id)
    base = _source_artifact(str(conversation["id"]), test_run_id, "base.txt", "base\n")

    with pytest.raises(ValidationError) as exc_info:
        create_diff_artifact_from_request(
            {
                "base_artifact_id": base["id"],
                "base_version_id": base["current_version_id"],
                "target_artifact_id": "art_missing",
                "target_version_id": "artv_missing",
            },
            test_run_id=test_run_id,
        )

    assert exc_info.value.code == "artifact_diff_target_not_found"
    assert list_artifacts(test_run_id=test_run_id, artifact_type="diff_preview") == []


def test_diff_service_checksum_mismatch_does_not_create_artifact(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-diff-checksum"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = _conversation(test_run_id, unique_id)
    base = _source_artifact(str(conversation["id"]), test_run_id, "base.txt", "base\n")
    target = _source_artifact(str(conversation["id"]), test_run_id, "target.txt", "target\n")

    with pytest.raises(ValidationError) as exc_info:
        create_diff_artifact_from_request(
            {
                "base_artifact_id": base["id"],
                "base_version_id": base["current_version_id"],
                "target_artifact_id": target["id"],
                "target_version_id": target["current_version_id"],
                "base_checksum": "sha256:not-the-stored-checksum",
            },
            test_run_id=test_run_id,
        )

    assert exc_info.value.code == "artifact_diff_checksum_mismatch"
    assert list_artifacts(test_run_id=test_run_id, artifact_type="diff_preview") == []


def test_diff_service_binary_content_does_not_create_artifact(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-diff-binary"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = _conversation(test_run_id, unique_id)
    base = _source_artifact(
        str(conversation["id"]),
        test_run_id,
        "blob.bin",
        b"\x00\x01binary",
        mime_type="application/octet-stream",
    )
    target = _source_artifact(str(conversation["id"]), test_run_id, "target.txt", "target\n")

    with pytest.raises(ValidationError) as exc_info:
        create_diff_artifact_from_request(
            {
                "base_artifact_id": base["id"],
                "base_version_id": base["current_version_id"],
                "target_artifact_id": target["id"],
                "target_version_id": target["current_version_id"],
            },
            test_run_id=test_run_id,
        )

    assert exc_info.value.code == "artifact_diff_unsupported_content"
    assert list_artifacts(test_run_id=test_run_id, artifact_type="diff_preview") == []
