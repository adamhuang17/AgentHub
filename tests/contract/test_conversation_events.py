from services.api.app.conversations.repository import (
    create_conversation,
    create_message,
    list_conversation_events,
)
from services.api.app.execution.events import append_event


def test_message_created_event_is_persisted_and_replayable(unique_id):
    test_run_id = f"{unique_id}-message-event"
    conversation = create_conversation(
        title=f"{unique_id} conversation events",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )

    message = create_message(
        conversation_id=str(conversation["id"]),
        message_type="text",
        content={"text": "Persist a message event."},
        mentions=[],
        references=[],
        reply_to_id=None,
        test_run_id=test_run_id,
    )

    events = list_conversation_events(str(conversation["id"]), test_run_id=test_run_id)
    assert [event["type"] for event in events] == ["message.created"]
    assert events[0]["payload_json"]["message_id"] == message["id"]
    assert events[0]["sequence"] == 1

    replayed = list_conversation_events(str(conversation["id"]), test_run_id=test_run_id)
    assert replayed == events


def test_after_sequence_returns_only_incremental_events(unique_id):
    test_run_id = f"{unique_id}-after-sequence"
    conversation = create_conversation(
        title=f"{unique_id} after sequence",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )

    first = append_event(
        conversation_id=str(conversation["id"]),
        event_type="task.created",
        task_id="task_first",
        payload={"task_id": "task_first", "status": "planned"},
    )
    second = append_event(
        conversation_id=str(conversation["id"]),
        event_type="plan.created",
        task_id="task_first",
        plan_id="plan_first",
        payload={"task_id": "task_first", "plan_id": "plan_first", "status": "ready"},
    )

    incremental = list_conversation_events(
        str(conversation["id"]),
        test_run_id=test_run_id,
        after_sequence=int(first["sequence"]),
    )

    assert [event["id"] for event in incremental] == [second["id"]]
    assert incremental[0]["sequence"] > first["sequence"]
