import pytest

from services.api.app.artifacts.repository import create_artifact
from services.api.app.conversations.repository import create_conversation, create_message, list_conversation_events
from services.api.app.memory.pinned_context import create_pin
from services.api.app.shared.errors import ValidationError


def _conversation(unique_id, suffix):
    test_run_id = f"{unique_id}-{suffix}"
    conversation = create_conversation(
        title=f"{unique_id} {suffix}",
        mode="group",
        agent_ids=[],
        test_run_id=test_run_id,
    )
    return conversation, test_run_id


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


def test_pin_message_success(unique_id):
    conversation, test_run_id = _conversation(unique_id, "pin-message")
    message = _message(conversation, "message to pin", test_run_id=test_run_id)

    pin = create_pin(
        conversation_id=conversation["id"],
        source_type="message",
        source_id=message["id"],
        note="keep",
        test_run_id=test_run_id,
    )

    assert pin["conversation_id"] == conversation["id"]
    assert pin["source_type"] == "message"
    assert pin["source_id"] == message["id"]


def test_pin_artifact_success(unique_id):
    conversation, test_run_id = _conversation(unique_id, "pin-artifact")
    artifact = create_artifact(
        conversation_id=conversation["id"],
        artifact_type="document",
        title="Spec.md",
        mime_type="text/markdown",
        content="# Spec",
        test_run_id=test_run_id,
    )

    pin = create_pin(
        conversation_id=conversation["id"],
        source_type="artifact",
        source_id=artifact["id"],
        note=None,
        test_run_id=test_run_id,
    )

    assert pin["source_id"] == artifact["id"]


def test_invalid_source_fails(unique_id):
    conversation, test_run_id = _conversation(unique_id, "invalid-source")

    with pytest.raises(ValidationError) as exc:
        create_pin(
            conversation_id=conversation["id"],
            source_type="message",
            source_id="msg_missing",
            note=None,
            test_run_id=test_run_id,
        )

    assert exc.value.code == "pin_source_invalid"


def test_cross_conversation_source_fails(unique_id):
    left, test_run_id = _conversation(unique_id, "left")
    right = create_conversation(
        title=f"{unique_id} right",
        mode="group",
        agent_ids=[],
        test_run_id=test_run_id,
    )
    message = _message(left, "left only", test_run_id=test_run_id)

    with pytest.raises(ValidationError) as exc:
        create_pin(
            conversation_id=right["id"],
            source_type="message",
            source_id=message["id"],
            note=None,
            test_run_id=test_run_id,
        )

    assert exc.value.code == "pin_source_invalid"


def test_pin_created_event_written(unique_id):
    conversation, test_run_id = _conversation(unique_id, "pin-event")
    message = _message(conversation, "message to pin", test_run_id=test_run_id)

    pin = create_pin(
        conversation_id=conversation["id"],
        source_type="message",
        source_id=message["id"],
        note=None,
        test_run_id=test_run_id,
    )
    events = list_conversation_events(conversation["id"], test_run_id=test_run_id)

    created = [event for event in events if event["type"] == "pin.created"]
    assert created
    assert created[-1]["payload"]["pin_id"] == pin["id"]
