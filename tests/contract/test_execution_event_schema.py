from services.api.app.conversations.repository import create_conversation, list_conversation_events
from services.api.app.execution.events import EVENT_TYPES, append_event
from tests.schema_assertions import assert_keys


def test_conversation_event_schema_fields(unique_id):
    test_run_id = f"{unique_id}-event-schema"
    conversation = create_conversation(
        title=f"{unique_id} event schema",
        mode="group_agent",
        agent_ids=[],
        test_run_id=test_run_id,
    )

    event = append_event(
        conversation_id=str(conversation["id"]),
        event_type="task.created",
        task_id="task_contract",
        payload={"task_id": "task_contract", "status": "planned"},
    )

    assert_keys(
        event,
        [
            "id",
            "conversation_id",
            "task_id",
            "plan_id",
            "step_id",
            "run_id",
            "artifact_id",
            "deployment_id",
            "sequence",
            "type",
            "payload_json",
            "created_at",
        ],
    )
    assert event["conversation_id"] == conversation["id"]
    assert event["task_id"] == "task_contract"
    assert event["plan_id"] is None
    assert event["sequence"] == 1
    assert event["payload_json"]["status"] == "planned"

    stored = list_conversation_events(str(conversation["id"]), test_run_id=test_run_id)
    assert stored[0]["id"] == event["id"]
    assert stored[0]["payload_json"] == event["payload_json"]


def test_required_core_execution_event_types_are_registered():
    for event_type in {
        "message.created",
        "planner.decision_created",
        "task.created",
        "plan.created",
        "step.created",
        "step.blocked",
        "agent_run.created",
        "agent_run.started",
        "agent_run.succeeded",
        "agent_run.failed",
        "artifact.created",
        "artifact.version_created",
        "diff.created",
        "review_request.created",
        "patch_application.applied",
        "patch_application.failed",
        "patch_application.conflict",
        "deployment_release.created",
        "deployment_release.published",
        "deployment_release.failed",
    }:
        assert event_type in EVENT_TYPES
