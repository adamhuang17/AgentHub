from services.api.app.agents.repository import list_agents
from services.api.app.artifacts.repository import create_artifact
from services.api.app.conversations.repository import (
    create_conversation,
    create_message,
    list_conversation_events,
    list_conversations,
    list_messages,
)


def test_conversation_list_response_shape(unique_id):
    test_run_id = f"{unique_id}-web-list"
    conversation = create_conversation(
        title=f"{unique_id} web list",
        mode="single",
        agent_ids=[],
        test_run_id=test_run_id,
    )

    items = list_conversations(test_run_id=test_run_id)

    assert items[0]["id"] == conversation["id"]
    for key in ["title", "mode", "last_active_at", "status"]:
        assert key in items[0]


def test_agent_list_response_shape():
    agents = list_agents(enabled=True)

    assert agents
    for key in [
        "name",
        "provider",
        "capability_tags",
        "enabled",
        "configured",
        "execution_enabled",
        "health_status",
    ]:
        assert key in agents[0]


def test_message_create_response_includes_cards_and_events_if_available(unique_id):
    test_run_id = f"{unique_id}-web-message"
    conversation = create_conversation(
        title=f"{unique_id} web message",
        mode="group",
        agent_ids=[],
        test_run_id=test_run_id,
    )
    artifact = create_artifact(
        conversation_id=conversation["id"],
        artifact_type="document",
        title="Spec.md",
        mime_type="text/markdown",
        content="# Spec",
        test_run_id=test_run_id,
    )

    message = create_message(
        conversation_id=conversation["id"],
        message_type="text",
        content={"text": "see artifact"},
        mentions=[],
        references=[{"type": "artifact", "artifact_id": artifact["id"]}],
        reply_to_id=None,
        test_run_id=test_run_id,
    )
    messages = list_messages(conversation["id"], test_run_id=test_run_id)
    events = list_conversation_events(conversation["id"], test_run_id=test_run_id)

    assert message["id"] == messages[-1]["id"]
    assert messages[-1]["artifact_cards"][0]["artifact_id"] == artifact["id"]
    assert events[-1]["type"] == "message.created"
