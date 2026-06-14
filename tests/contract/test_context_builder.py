import json

from services.api.app.artifacts.repository import append_artifact_version, create_artifact
from services.api.app.conversations.repository import create_conversation, create_message
from services.api.app.memory.context_builder import build_context_bundle
from services.api.app.memory.pinned_context import create_pin


def _conversation(unique_id, suffix="context"):
    return create_conversation(
        title=f"{unique_id} {suffix}",
        mode="group",
        agent_ids=[],
        test_run_id=f"{unique_id}-{suffix}",
    )


def _message(conversation, text, *, test_run_id):
    return create_message(
        conversation_id=conversation["id"],
        message_type="text",
        content={"text": text},
        mentions=[],
        references=[],
        reply_to_id=None,
        test_run_id=test_run_id,
    )


def test_recent_messages_enter_context(unique_id):
    test_run_id = f"{unique_id}-recent"
    conversation = _conversation(unique_id, "recent")
    _message(conversation, "first context line", test_run_id=test_run_id)
    _message(conversation, "second context line", test_run_id=test_run_id)

    bundle = build_context_bundle(conversation["id"], test_run_id=test_run_id)

    assert bundle["conversation_id"] == conversation["id"]
    assert [item["text"] for item in bundle["recent_messages"]] == [
        "first context line",
        "second context line",
    ]
    assert bundle["context_summary"]["recent_message_count"] == 2


def test_message_pin_resolves_by_reference(unique_id):
    test_run_id = f"{unique_id}-message-pin"
    conversation = _conversation(unique_id, "message-pin")
    message = _message(conversation, "pin this message", test_run_id=test_run_id)
    pin = create_pin(
        conversation_id=conversation["id"],
        source_type="message",
        source_id=message["id"],
        note="important",
        test_run_id=test_run_id,
    )

    bundle = build_context_bundle(conversation["id"], test_run_id=test_run_id)

    pinned = bundle["pinned_context"][0]
    assert pinned["id"] == pin["id"]
    assert pinned["source_id"] == message["id"]
    assert pinned["resolved"]["id"] == message["id"]
    assert pinned["resolved"]["text"] == "pin this message"


def test_artifact_pin_resolves_metadata(unique_id):
    test_run_id = f"{unique_id}-artifact-pin"
    conversation = _conversation(unique_id, "artifact-pin")
    artifact = create_artifact(
        conversation_id=conversation["id"],
        artifact_type="document",
        title="Spec.md",
        mime_type="text/markdown",
        content="# Spec",
        test_run_id=test_run_id,
    )
    create_pin(
        conversation_id=conversation["id"],
        source_type="artifact",
        source_id=artifact["id"],
        note=None,
        test_run_id=test_run_id,
    )

    bundle = build_context_bundle(conversation["id"], test_run_id=test_run_id)

    resolved = bundle["pinned_context"][0]["resolved"]
    assert resolved["artifact_id"] == artifact["id"]
    assert resolved["current_version_id"] == artifact["current_version_id"]
    assert resolved["checksum"] == artifact["checksum"]
    assert "content" not in resolved


def test_artifact_version_pin_resolves_version_metadata(unique_id):
    test_run_id = f"{unique_id}-artifact-version-pin"
    conversation = _conversation(unique_id, "artifact-version-pin")
    artifact = create_artifact(
        conversation_id=conversation["id"],
        artifact_type="document",
        title="Spec.md",
        mime_type="text/markdown",
        content="# v1",
        test_run_id=test_run_id,
    )
    version = append_artifact_version(
        artifact["id"],
        content="# v2",
        parent_version_id=artifact["current_version_id"],
        test_run_id=test_run_id,
    )
    create_pin(
        conversation_id=conversation["id"],
        source_type="artifact_version",
        source_id=version["version_id"],
        note=None,
        test_run_id=test_run_id,
    )

    bundle = build_context_bundle(conversation["id"], test_run_id=test_run_id)

    resolved = bundle["pinned_context"][0]["resolved"]
    assert resolved["artifact_id"] == artifact["id"]
    assert resolved["version_id"] == version["version_id"]
    assert resolved["version"] == 2
    assert resolved["parent_version_id"] == artifact["current_version_id"]


def test_binary_artifact_context_is_metadata_only(unique_id):
    test_run_id = f"{unique_id}-binary"
    conversation = _conversation(unique_id, "binary")
    artifact = create_artifact(
        conversation_id=conversation["id"],
        artifact_type="binary_file",
        title="payload.bin",
        mime_type="application/octet-stream",
        content=b"\x00\x01\x02binary-payload",
        test_run_id=test_run_id,
    )
    create_pin(
        conversation_id=conversation["id"],
        source_type="artifact",
        source_id=artifact["id"],
        note=None,
        test_run_id=test_run_id,
    )

    bundle = build_context_bundle(conversation["id"], test_run_id=test_run_id)
    blob = json.dumps(bundle, ensure_ascii=False)

    assert "binary-payload" not in blob
    assert artifact["checksum"] in blob


def test_long_message_is_truncated(monkeypatch, unique_id):
    test_run_id = f"{unique_id}-truncate"
    monkeypatch.setenv("AGENTHUB_CONTEXT_MAX_MESSAGE_CHARS", "12")
    monkeypatch.setenv("AGENTHUB_CONTEXT_MAX_TOTAL_CHARS", "20")
    conversation = _conversation(unique_id, "truncate")
    _message(conversation, "abcdefghijklmnopqrstuvwxyz", test_run_id=test_run_id)

    bundle = build_context_bundle(conversation["id"], test_run_id=test_run_id)

    assert bundle["recent_messages"][0]["text"] == "abcdefghijkl"
    assert bundle["recent_messages"][0]["truncated"] is True
    assert bundle["context_summary"]["truncated"] is True


def test_context_redacts_secret_like_material(unique_id):
    test_run_id = f"{unique_id}-secret"
    conversation = _conversation(unique_id, "secret")
    _message(
        conversation,
        "API key: sk-proj-abcdefghijklmnopqrstuvwxyz1234567890\nnormal line",
        test_run_id=test_run_id,
    )

    bundle = build_context_bundle(conversation["id"], test_run_id=test_run_id)
    blob = json.dumps(bundle, ensure_ascii=False)

    assert "sk-proj-" not in blob
    assert "normal line" in blob
