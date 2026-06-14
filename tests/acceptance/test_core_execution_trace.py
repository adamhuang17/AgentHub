from tests.support import create_conversation, enabled_agents, item_list, post_message, task_from_message


def _turn_decision(*steps):
    return {
        "decision_type": "plan_task",
        "target_type": "orchestrator",
        "target_source": "auto_orchestrate",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": "Create a durable execution trace.",
        "reason": "Core execution trace acceptance fixture",
        "confidence": "high",
        "steps": list(steps),
        "clarification_question": None,
    }


def _step(kind, *, required_capabilities=None):
    return {
        "kind": kind,
        "objective": f"{kind} trace step",
        "required_capabilities": required_capabilities or [],
        "depends_on": [],
        "expected_output": {"kind": kind},
    }


def _event_types(api_request, conversation_id):
    _, payload, _ = api_request("GET", f"/api/conversations/{conversation_id}/events", expected=200)
    events = item_list(payload)
    return events, [event["type"] for event in events]


def test_core_execution_trace_replays_plan_task_and_blocked_step(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} core execution trace")
    _, message, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "Plan this task and keep a durable trace."},
            "turn_decision": _turn_decision(_step("analysis", required_capabilities=["missing-trace-capability"])),
        },
        expected=201,
    )
    task_id = task_from_message(message)

    events, event_types = _event_types(api_request, conversation["id"])
    for expected_type in {
        "message.created",
        "planner.decision_created",
        "task.created",
        "plan.created",
        "step.created",
        "step.blocked",
    }:
        assert expected_type in event_types, events
    assert [event["sequence"] for event in events] == sorted(event["sequence"] for event in events)
    assert len({event["sequence"] for event in events}) == len(events)

    blocked = next(event for event in events if event["type"] == "step.blocked")
    assert blocked["task_id"] == task_id
    assert blocked["payload_json"]["blocked_reason"] == "no_capability_match"

    _, task, _ = api_request("GET", f"/api/tasks/{task_id}", expected=200)
    assert task["id"] == task_id
    assert task["plan"]["id"]
    assert task["steps"][0]["status"] == "blocked"
    assert isinstance(task.get("runs"), list)
    assert "events" in task and item_list({"items": task["events"]})
    assert task["event_summary"]["types"]["step.blocked"] == 1

    _, replay_payload, _ = api_request("GET", f"/api/conversations/{conversation['id']}/events", expected=200)
    assert item_list(replay_payload) == events

    after = events[0]["sequence"]
    _, incremental_payload, _ = api_request(
        "GET",
        f"/api/conversations/{conversation['id']}/events?after_sequence={after}",
        expected=200,
    )
    incremental = item_list(incremental_payload)
    assert incremental
    assert all(event["sequence"] > after for event in incremental)


def test_core_execution_trace_records_direct_response_run_terminal_state(api_request, unique_id):
    agent = enabled_agents(api_request, minimum=1)[0]
    conversation = create_conversation(
        api_request,
        f"{unique_id} direct response trace",
        mode="private_agent",
        agent_ids=[agent["id"]],
    )
    message = post_message(api_request, conversation["id"], "Create a direct response run trace.")

    _, run, _ = api_request(
        "POST",
        "/api/runs",
        {
            "source_type": "message",
            "source_message_id": message["id"],
            "target_agent_id": agent["id"],
            "run_mode": "direct_response",
            "instruction": "Reply with one sentence if the adapter is configured.",
            "context_bundle": {},
            "workspace_ref": None,
            "allowed_tools": [],
            "expected_artifacts": [],
        },
        expected=201,
    )

    events, event_types = _event_types(api_request, conversation["id"])
    assert "agent_run.created" in event_types
    assert "agent_run.started" in event_types
    assert {"agent_run.failed", "agent_run.succeeded"} & set(event_types)
    assert run["status"] in {"failed", "succeeded"}
    terminal = "agent_run.succeeded" if run["status"] == "succeeded" else "agent_run.failed"
    terminal_event = next(event for event in events if event["type"] == terminal)
    assert terminal_event["run_id"] == run["id"]
    assert terminal_event["payload_json"]["status"] == run["status"]


def test_core_execution_trace_records_artifact_creation_and_incremental_replay(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} artifact trace")
    _, artifact, _ = api_request(
        "POST",
        "/api/artifacts",
        {
            "conversation_id": conversation["id"],
            "type": "document",
            "title": f"{unique_id} Trace Note",
            "mime_type": "text/markdown",
            "content": "# Trace\n\nPersisted artifact event.",
        },
        expected=201,
    )

    events, event_types = _event_types(api_request, conversation["id"])
    assert "artifact.created" in event_types
    assert "artifact.version_created" in event_types
    artifact_events = [event for event in events if event["artifact_id"] == artifact["id"]]
    assert [event["type"] for event in artifact_events] == ["artifact.created", "artifact.version_created"]

    _, incremental_payload, _ = api_request(
        "GET",
        f"/api/conversations/{conversation['id']}/events?after_sequence={artifact_events[0]['sequence']}",
        expected=200,
    )
    incremental = item_list(incremental_payload)
    assert [event["type"] for event in incremental] == ["artifact.version_created"]
