from tests.support import (
    assert_no_run_succeeded,
    conversation_tasks,
    create_conversation,
    enabled_agents,
    item_list,
    task_from_message,
    wait_task,
)


def _turn_decision(*steps, decision_type="plan_task", goal="A6 injected turn task"):
    return {
        "decision_type": decision_type,
        "target_type": "orchestrator" if decision_type != "no_action" else "none",
        "target_source": "auto_orchestrate" if decision_type != "no_action" else "none",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": goal,
        "steps": list(steps),
        "reason": "A6 acceptance injected turn decision",
        "confidence": "high",
        "clarification_question": None,
    }


def _step(kind, *, required_capabilities=None, depends_on=None, expected_output=None):
    return {
        "kind": kind,
        "objective": f"{kind} objective from injected turn decision",
        "required_capabilities": required_capabilities or [],
        "depends_on": depends_on or [],
        "expected_output": expected_output or {"kind": kind},
    }


def _no_action(reason="turn router says no task"):
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


def _post_turn_message(api_request, conversation_id, text, turn_decision, expected={200, 201}):
    _, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation_id}/messages",
        {
            "message_type": "text",
            "content": {"text": text},
            "turn_decision": turn_decision,
        },
        expected=expected,
    )
    return payload


def test_a6_non_task_decision_does_not_create_task(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} a6 non task")

    message = _post_turn_message(
        api_request,
        conversation["id"],
        "Keyword-looking text is ignored by local classifiers.",
        _no_action(),
    )

    assert "task_id" not in message
    assert conversation_tasks(api_request, conversation["id"]) == []


def test_a6_single_step_task_decision_creates_one_step(api_request, unique_id):
    agents = enabled_agents(api_request, minimum=2)
    conversation = create_conversation(
        api_request,
        f"{unique_id} a6 single step",
        mode="group_agent",
        agent_ids=[agent["id"] for agent in agents[:2]],
    )

    message = _post_turn_message(
        api_request,
        conversation["id"],
        "The route must persist the injected single step.",
        _turn_decision(_step("implementation", required_capabilities=["code"])),
    )
    task = wait_task(api_request, task_from_message(message), terminal=("planned",))
    assert task["status"] == "planned"

    plan = task.get("plan") or {}
    steps = plan.get("steps") or task.get("steps") or []
    assert plan.get("id"), f"Task must include a persisted plan: {task}"
    assert len(steps) == 1
    step = steps[0]
    assert step["kind"] == "implementation"
    assert step["assigned_agent_id"] is None
    assert step["status"] == "blocked"
    assert step["dispatch_source"] == "blocked"
    assert step["blocked_reason"] == "agent_not_configured"
    assert "configured=false" in step["dispatch_reason"]
    assert_no_run_succeeded(task)


def test_a6_multi_step_task_decision_creates_at_most_three_steps(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} a6 multi step")

    message = _post_turn_message(
        api_request,
        conversation["id"],
        "Natural language here is only persisted message text.",
        _turn_decision(
            _step("analysis", expected_output={"kind": "analysis"}),
            _step("implementation", required_capabilities=["code"], depends_on=["step-1"]),
            _step("review", required_capabilities=["review"], depends_on=["step-2"]),
        ),
    )
    task = wait_task(api_request, task_from_message(message), terminal=("planned",))
    steps = task["steps"]

    assert len(steps) == 3
    assert [step["kind"] for step in steps] == ["analysis", "implementation", "review"]
    assert steps[0]["depends_on"] == []
    assert steps[1]["depends_on"] == [steps[0]["id"]]
    assert steps[2]["depends_on"] == [steps[1]["id"]]
    for step in steps:
        assert step["dispatch_reason"]
        assert step["dispatch_source"] in {"capability", "blocked"}
    assert_no_run_succeeded(task)


def test_a6_invalid_step_kind_is_rejected_without_task(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} a6 invalid kind")

    _, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "The invalid kind comes from planner output, not text."},
            "turn_decision": _turn_decision(_step("deploy")),
        },
        expected=400,
    )

    assert payload["error_code"] == "turn_router_invalid_output"
    assert conversation_tasks(api_request, conversation["id"]) == []
    assert_no_run_succeeded(payload)


def test_a6_no_matching_agent_creates_blocked_step(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} a6 blocked step")

    message = _post_turn_message(
        api_request,
        conversation["id"],
        "Turn router asks for analysis, but no enabled profile has that capability.",
        _turn_decision(_step("analysis")),
    )
    task = wait_task(api_request, task_from_message(message), terminal=("planned",))
    steps = item_list({"items": task["steps"]})

    assert len(steps) == 1
    step = steps[0]
    assert step["kind"] == "analysis"
    assert step["assigned_agent_id"] is None
    assert step["status"] == "blocked"
    assert step["dispatch_source"] == "blocked"
    assert step["blocked_reason"] == "no_capability_match"
    assert_no_run_succeeded(task)


def test_a6_turn_router_not_configured_returns_explicit_error(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} a6 router disabled")

    _, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "Routing was requested but no turn decision was supplied."},
            "turn_route": True,
        },
        expected=503,
    )

    assert payload["error_code"] == "turn_router_not_configured"
    assert payload["recovery_hint"]
    assert conversation_tasks(api_request, conversation["id"]) == []
    assert_no_run_succeeded(payload)


def test_a6_mentions_still_use_a5_dispatch_without_turn_router(api_request, unique_id):
    target_agent = enabled_agents(api_request, minimum=1)[0]
    conversation = create_conversation(
        api_request,
        f"{unique_id} a6 mention bypasses planner",
        mode="group_agent",
        agent_ids=[target_agent["id"]],
    )

    _, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": f"@{target_agent['name']} use mention dispatch"},
            "mentions": [{"agent_id": target_agent["id"], "display": target_agent["name"]}],
            "turn_decision": _turn_decision(_step("deploy")),
        },
        expected={200, 201},
    )
    task = wait_task(api_request, task_from_message(payload), terminal=("planned",))
    step = task["steps"][0]
    assert step["assigned_agent_id"] == target_agent["id"]
    assert step["dispatch_source"] == "mention"
    assert "explicit_mention" in step["dispatch_reason"]
    assert_no_run_succeeded(task)
