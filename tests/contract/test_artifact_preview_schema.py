from pathlib import Path

import pytest

from services.api.app.artifacts.diff_service import create_diff_artifact_from_request
from services.api.app.artifacts.office import DOCX_MIME_TYPE, PPTX_MIME_TYPE, render_docx, render_pptx
from services.api.app.artifacts.repository import create_artifact
from services.api.app.conversations.repository import create_conversation
from services.api.app.preview.service import preview_artifact
from services.api.app.shared.errors import ValidationError


def _store_dir(test_run_id):
    return Path("var") / "test-artifacts" / test_run_id


def _stored_path(root, storage_key):
    return root.joinpath(*str(storage_key).split("/"))


def _conversation(test_run_id, unique_id):
    return create_conversation(
        title=f"{unique_id} artifact preview",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )


def test_document_preview_is_read_only_text(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-preview-document"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = _conversation(test_run_id, unique_id)
    artifact = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="document",
        title="notes.md",
        mime_type="text/markdown",
        content="# Notes\n\nRead-only preview.\n",
        test_run_id=test_run_id,
    )

    preview = preview_artifact(str(artifact["id"]), test_run_id=test_run_id)

    assert preview["preview_type"] == "text"
    assert preview["read_only"] is True
    assert preview["source"] == "artifact_store"
    assert preview["artifact_id"] == artifact["id"]
    assert preview["version_id"] == artifact["current_version_id"]
    assert preview["checksum"] == artifact["checksum"]
    assert preview["content"] == "# Notes\n\nRead-only preview.\n"
    assert "url" not in preview
    assert "external_url" not in preview
    assert preview["status"] != "published"


def test_diff_artifact_preview_is_structured(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-preview-diff"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = _conversation(test_run_id, unique_id)
    base = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="source_file",
        title="app.py",
        mime_type="text/x-python",
        content="print('hello')\n",
        test_run_id=test_run_id,
    )
    target = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="source_file",
        title="app.py",
        mime_type="text/x-python",
        content="print('hello world')\n",
        test_run_id=test_run_id,
    )
    diff = create_diff_artifact_from_request(
        {
            "base_artifact_id": base["id"],
            "base_version_id": base["current_version_id"],
            "target_artifact_id": target["id"],
            "target_version_id": target["current_version_id"],
            "path": "app.py",
            "type": "source_diff",
        },
        test_run_id=test_run_id,
    )

    preview = preview_artifact(str(diff["diff_artifact_id"]), test_run_id=test_run_id)

    assert preview["preview_type"] == "structured_diff"
    assert preview["read_only"] is True
    assert preview["type"] == "source_diff"
    assert preview["base_artifact_id"] == base["id"]
    assert preview["target_artifact_id"] == target["id"]
    assert preview["files"][0]["path"] == "app.py"
    assert preview["hunks"][0]["file_path"] == "app.py"
    assert preview["additions"] == 1
    assert preview["deletions"] == 1
    assert "url" not in preview
    assert "external_url" not in preview


def test_office_artifact_preview_extracts_downloadable_content(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-preview-office"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = _conversation(test_run_id, unique_id)
    document = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="word_doc",
        title="brief.docx",
        mime_type=DOCX_MIME_TYPE,
        content=render_docx("# Project Brief\n\nShip the AgentHub flow.", title="Project Brief"),
        test_run_id=test_run_id,
    )
    deck = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="presentation",
        title="brief.pptx",
        mime_type=PPTX_MIME_TYPE,
        content=render_pptx("# Project Brief\n\n- Ship the AgentHub flow", title="Project Brief"),
        test_run_id=test_run_id,
    )

    document_preview = preview_artifact(str(document["id"]), test_run_id=test_run_id)
    deck_preview = preview_artifact(str(deck["id"]), test_run_id=test_run_id)

    assert document_preview["preview_type"] == "office_document"
    assert "Project Brief" in document_preview["content"]
    assert "Ship the AgentHub flow." in document_preview["content"]
    assert deck_preview["preview_type"] == "office_document"
    assert "Slide 1" in deck_preview["content"]
    assert "Project Brief" in deck_preview["content"]


def test_preview_checksum_mismatch_fails(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-preview-checksum"
    store_root = _store_dir(test_run_id)
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(store_root))
    conversation = _conversation(test_run_id, unique_id)
    artifact = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="document",
        title="notes.txt",
        mime_type="text/plain",
        content="before\n",
        test_run_id=test_run_id,
    )
    _stored_path(store_root, artifact["storage_key"]).write_text("after\n", encoding="utf-8")

    with pytest.raises(ValidationError) as exc_info:
        preview_artifact(str(artifact["id"]), test_run_id=test_run_id)

    assert exc_info.value.code == "artifact_preview_checksum_mismatch"


def test_binary_preview_is_unsupported(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-preview-binary"
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(_store_dir(test_run_id)))
    conversation = _conversation(test_run_id, unique_id)
    artifact = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="source_file",
        title="blob.bin",
        mime_type="application/octet-stream",
        content=b"\x00\x01binary",
        test_run_id=test_run_id,
    )

    with pytest.raises(ValidationError) as exc_info:
        preview_artifact(str(artifact["id"]), test_run_id=test_run_id)

    assert exc_info.value.code == "artifact_preview_unsupported"
