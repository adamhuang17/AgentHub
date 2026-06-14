from pathlib import Path

import pytest

from services.api.app.artifacts.repository import (
    append_artifact_version,
    create_artifact,
    read_artifact_download,
)
from services.api.app.conversations.repository import create_conversation
from services.api.app.shared.errors import ValidationError


def _store_dir(test_run_id):
    return Path("var") / "test-artifacts" / test_run_id


def _stored_path(root, storage_key):
    return root.joinpath(*str(storage_key).split("/"))


def test_source_file_download_reads_current_version(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-artifact-download"
    store_root = _store_dir(test_run_id)
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(store_root))
    conversation = create_conversation(
        title=f"{unique_id} artifact download",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )
    artifact = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="source_file",
        title="main.py",
        mime_type="text/x-python",
        content="print('hello')\n",
        test_run_id=test_run_id,
    )

    payload = read_artifact_download(str(artifact["id"]), test_run_id=test_run_id)

    assert payload["artifact_id"] == artifact["id"]
    assert payload["version_id"] == artifact["current_version_id"]
    assert payload["version"] == 1
    assert payload["checksum"] == artifact["checksum"]
    assert payload["mime_type"] == "text/x-python"
    assert payload["filename"] == "main.py"
    assert payload["content"] == b"print('hello')\n"


def test_document_download_reads_markdown_bytes(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-artifact-download-document"
    store_root = _store_dir(test_run_id)
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(store_root))
    conversation = create_conversation(
        title=f"{unique_id} artifact download document",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )
    artifact = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="document",
        title="notes.md",
        mime_type="text/markdown",
        content="# Notes\n\nDownload only.\n",
        test_run_id=test_run_id,
    )

    payload = read_artifact_download(str(artifact["id"]), test_run_id=test_run_id)

    assert payload["mime_type"] == "text/markdown"
    assert payload["filename"] == "notes.md"
    assert payload["content"] == b"# Notes\n\nDownload only.\n"


def test_binary_file_download_preserves_raw_bytes(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-artifact-download-binary"
    store_root = _store_dir(test_run_id)
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(store_root))
    conversation = create_conversation(
        title=f"{unique_id} artifact download binary",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )
    binary_content = b"\x00\x01agenthub\xff\x10"
    artifact = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="binary_file",
        title="bundle.bin",
        mime_type="application/octet-stream",
        content=binary_content,
        test_run_id=test_run_id,
    )

    payload = read_artifact_download(str(artifact["id"]), test_run_id=test_run_id)

    assert payload["mime_type"] == "application/octet-stream"
    assert payload["filename"] == "bundle.bin"
    assert payload["content"] == binary_content


def test_download_can_read_specific_version(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-artifact-download-version"
    store_root = _store_dir(test_run_id)
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(store_root))
    conversation = create_conversation(
        title=f"{unique_id} artifact download version",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )
    artifact = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="source_file",
        title="main.py",
        mime_type="text/x-python",
        content="print('v1')\n",
        test_run_id=test_run_id,
    )
    append_artifact_version(
        str(artifact["id"]),
        content="print('v2')\n",
        parent_version_id=str(artifact["current_version_id"]),
        test_run_id=test_run_id,
    )

    payload = read_artifact_download(str(artifact["id"]), test_run_id=test_run_id, version=1)

    assert payload["version"] == 1
    assert payload["version_id"] == artifact["current_version_id"]
    assert payload["content"] == b"print('v1')\n"


def test_content_download_checksum_mismatch_has_error_code(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-artifact-download-checksum"
    store_root = _store_dir(test_run_id)
    monkeypatch.setenv("AGENTHUB_ARTIFACT_STORE_DIR", str(store_root))
    conversation = create_conversation(
        title=f"{unique_id} artifact download checksum",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )
    artifact = create_artifact(
        conversation_id=str(conversation["id"]),
        artifact_type="source_file",
        title="main.py",
        mime_type="text/x-python",
        content="print('before')\n",
        test_run_id=test_run_id,
    )
    _stored_path(store_root, artifact["storage_key"]).write_text("print('after')\n", encoding="utf-8")

    with pytest.raises(ValidationError) as exc_info:
        read_artifact_download(str(artifact["id"]), test_run_id=test_run_id)

    assert exc_info.value.code == "artifact_checksum_mismatch"
