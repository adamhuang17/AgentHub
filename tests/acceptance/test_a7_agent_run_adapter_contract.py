from tests.support import (
    assert_no_run_succeeded,
    conversation_messages,
    conversation_tasks,
    create_conversation,
    enabled_agents,
    item_list,
    wait_task,
)


def _turn_plan_task(kind="implementation", *, required_capabilities=None):
    return {
        "decision_type": "plan_task",
        "target_type": "orchestrator",
        "target_source": "auto_orchestrate",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": f"A7 planned step for {kind}",
        "reason": "A7 acceptance fixture",
        "confidence": "high",
        "steps": [
            {
                "kind": kind,
                "objective": f"{kind} objective",
                "required_capabilities": required_capabilities or [],
                "depends_on": [],
                "expected_output": {"kind": kind},
            }
        ],
        "clarification_question": None,
    }


def _turn_direct_response(agent_id):
    return {
        "decision_type": "direct_response",
        "target_type": "agent",
        "target_source": "private_chat",
        "target_agent_id": agent_id,
        "target_agent_ids": [agent_id],
        "goal": None,
        "steps": [],
        "reason": "A7 direct response fixture",
        "confidence": "high",
        "clarification_question": None,
    }


def _post_message(api_request, conversation_id, body, expected={200, 201}):
    _, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation_id}/messages",
        body,
        expected=expected,
    )
    return payload


def _run_events(api_request, run_id):
    _, payload, _ = api_request("GET", f"/api/runs/{run_id}/events", expected=200)
    return item_list(payload)


def _assert_provider_not_configured_run(api_request, run_id):
    _, run, _ = api_request("GET", f"/api/runs/{run_id}", expected=200)
    events = _run_events(api_request, run_id)
    event_types = [event["type"] for event in events]

    assert run["status"] == "failed"
    assert run["error_code"] == "provider_not_configured"
    _, health, _ = api_request("GET", f"/api/agents/{run['target_agent_id']}/adapter-health", expected=200)
    assert health["configured"] is False
    assert health["error_code"] in {"provider_not_configured", "credential_missing", "adapter_unavailable"}
    assert event_types == ["run_created", "run_started", "provider_not_configured", "run_failed"]
    assert [event["sequence"] for event in events] == [1, 2, 3, 4]
    assert "run_succeeded" not in event_types
    assert events[2]["payload"]["error_code"] == "provider_not_configured"
    assert events[2]["payload"]["recovery_hint"]
    assert_no_run_succeeded(run)
    assert_no_run_succeeded(events)
    return run, events


def _assert_explicit_failed_run(api_request, run_id):
    _, run, _ = api_request("GET", f"/api/runs/{run_id}", expected=200)
    events = _run_events(api_request, run_id)
    event_types = [event["type"] for event in events]

    assert run["status"] == "failed"
    assert run["error_code"] in {
        "provider_not_configured",
        "credential_missing",
        "adapter_unavailable",
        "unsupported_provider",
    }
    assert event_types[0:2] == ["run_created", "run_started"]
    assert event_types[-1] == "run_failed"
    assert "run_succeeded" not in event_types
    failure_events = [event for event in events if event["type"] in {"provider_not_configured", "adapter_error"}]
    assert failure_events
    assert failure_events[-1]["payload"]["error_code"] == run["error_code"]
    assert failure_events[-1]["payload"]["recovery_hint"]
    assert_no_run_succeeded(run)
    assert_no_run_succeeded(events)
    return run, events


def test_direct_response_creates_failed_run_with_provider_not_configured(api_request, unique_id):
    agent = enabled_agents(api_request, minimum=1)[0]
    conversation = create_conversation(
        api_request,
        f"{unique_id} a7 direct response",
        mode="private_agent",
        agent_ids=[agent["id"]],
    )

    message = _post_message(
        api_request,
        conversation["id"],
        {
            "message_type": "text",
            "content": {"text": "This direct response must create a failed AgentRun."},
            "turn_decision": _turn_direct_response(agent["id"]),
        },
    )

    assert message["run_id"]
    assert message["agent_run"]["run_mode"] == "direct_response"
    assert conversation_tasks(api_request, conversation["id"]) == []
    assert len(conversation_messages(api_request, conversation["id"])) == 1
    _assert_provider_not_configured_run(api_request, message["run_id"])


def test_planned_step_creates_failed_run_with_explicit_provider_error(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} a7 planned step")
    message = _post_message(
        api_request,
        conversation["id"],
        {
            "message_type": "text",
            "content": {"text": "Create one implementation step for A7."},
            "turn_decision": _turn_plan_task("implementation", required_capabilities=["code"]),
        },
    )
    task = wait_task(api_request, message["task_id"], terminal=("planned",))
    step = task["steps"][0]

    _, run, _ = api_request(
        "POST",
        "/api/runs",
        {
            "source_type": "plan_step",
            "plan_step_id": step["id"],
            "run_mode": "planned_step",
            "instruction": "Execute the existing planned step.",
            "context_bundle": {},
            "workspace_ref": None,
            "allowed_tools": [],
            "expected_artifacts": [],
        },
        expected=201,
    )

    assert run["source_type"] == "plan_step"
    assert run["plan_step_id"] == step["id"]
    assert run["target_agent_id"] == step["assigned_agent_id"]
    _assert_explicit_failed_run(api_request, run["id"])


def test_blocked_plan_step_cannot_create_run(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} a7 blocked step")
    message = _post_message(
        api_request,
        conversation["id"],
        {
            "message_type": "text",
            "content": {"text": "Create an unmatched analysis step."},
            "turn_decision": _turn_plan_task("analysis"),
        },
    )
    task = wait_task(api_request, message["task_id"], terminal=("planned",))
    step = task["steps"][0]
    assert step["status"] == "blocked"

    _, payload, _ = api_request(
        "POST",
        "/api/runs",
        {"source_type": "plan_step", "plan_step_id": step["id"], "run_mode": "planned_step"},
        expected=400,
    )

    assert payload["code"] == "plan_step_blocked"


def test_unknown_agent_and_unknown_plan_step_cannot_create_run(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} a7 unknown sources")
    message = _post_message(
        api_request,
        conversation["id"],
        {
            "message_type": "text",
            "content": {"text": "Source message for unknown agent run."},
            "turn_decision": {
                "decision_type": "no_action",
                "target_type": "none",
                "target_source": "none",
                "target_agent_id": None,
                "target_agent_ids": [],
                "goal": None,
                "reason": "message source fixture only",
                "confidence": "high",
                "steps": [],
                "clarification_question": None,
            },
        },
    )

    _, unknown_agent, _ = api_request(
        "POST",
        "/api/runs",
        {
            "source_type": "message",
            "source_message_id": message["id"],
            "target_agent_id": f"missing-{unique_id}",
            "run_mode": "direct_response",
        },
        expected=400,
    )
    assert unknown_agent["code"] == "unknown_agent"

    _, unknown_step, _ = api_request(
        "POST",
        "/api/runs",
        {"source_type": "plan_step", "plan_step_id": f"missing-step-{unique_id}", "run_mode": "planned_step"},
        expected=404,
    )
    assert unknown_step["error"] == "not_found"
