from tests.support import create_conversation, conversation_tasks, item_list, task_from_message


def _turn_decision(*steps, decision_type="plan_task", goal="Contract routed task"):
    return {
        "decision_type": decision_type,
        "target_type": "orchestrator" if decision_type != "no_action" else "none",
        "target_source": "auto_orchestrate" if decision_type != "no_action" else "none",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": goal,
        "steps": list(steps),
        "reason": "contract injected turn decision",
        "confidence": "high",
        "clarification_question": None,
    }


def _step(kind, objective=None, required_capabilities=None, depends_on=None):
    return {
        "kind": kind,
        "objective": objective or f"{kind} objective",
        "required_capabilities": required_capabilities or [],
        "depends_on": depends_on or [],
        "expected_output": {"kind": kind},
    }


def _no_action(reason="contract no task"):
    return {
        "decision_type": "no_action",
        "target_type": "none",
        "target_source": "none",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": None,
        "steps": [],
        "reason": reason,
        "confidence": "high",
        "clarification_question": None,
    }


def _post_turn_message(api_request, conversation_id, text, decision, expected={200, 201}):
    _, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation_id}/messages",
        {
            "message_type": "text",
            "content": {"text": text},
            "turn_decision": decision,
        },
        expected=expected,
    )
    return payload


def test_non_mentioned_task_message_creates_capability_plan(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} planner schema")
    message = _post_turn_message(
        api_request,
        conversation["id"],
        "This text is not classified by local keywords.",
        _turn_decision(
            _step("implementation", required_capabilities=["code"]),
            _step("review", required_capabilities=["review"], depends_on=["step-1"]),
        ),
    )

    task_id = task_from_message(message)
    _, task, _ = api_request("GET", f"/api/tasks/{task_id}", expected=200)
    assert task["status"] == "planned"
    assert task["created_by_message_id"] == message["id"]
    assert task["plan"]["status"] == "ready"

    steps = task["steps"]
    assert [step["kind"] for step in steps] == ["implementation", "review"]
    assert steps[0]["depends_on"] == []
    assert steps[1]["depends_on"] == [steps[0]["id"]]
    for step in steps:
        assert step["assigned_agent_id"] is None
        assert step["blocked_reason"] == "agent_not_configured"
        assert step["status"] == "blocked"
        assert step["dispatch_source"] == "blocked"
        assert "configured=false" in step["dispatch_reason"]
        assert step["expected_output"] == {"kind": step["kind"]}


def test_non_task_message_does_not_create_task(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} non task planner")
    message = _post_turn_message(
        api_request,
        conversation["id"],
        "Any text may be non-task when the planner says so.",
        _no_action("contract no_action"),
    )
    assert "task_id" not in message
    assert conversation_tasks(api_request, conversation["id"]) == []


def test_unmatched_task_step_is_blocked_at_step_level(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} blocked planner")
    message = _post_turn_message(
        api_request,
        conversation["id"],
        "No keyword routing is allowed here.",
        _turn_decision(_step("analysis")),
    )

    task_id = task_from_message(message)
    _, task, _ = api_request("GET", f"/api/tasks/{task_id}", expected=200)
    assert task["status"] == "planned"
    assert task["plan"]["status"] == "ready"
    steps = item_list({"items": task["steps"]})
    assert len(steps) == 1
    step = steps[0]
    assert step["kind"] == "analysis"
    assert step["assigned_agent_id"] is None
    assert step["status"] == "blocked"
    assert step["dispatch_source"] == "blocked"
    assert step["blocked_reason"] == "no_capability_match"
