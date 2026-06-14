from tests.support import (
    assert_no_run_succeeded,
    conversation_messages,
    conversation_tasks,
    create_conversation,
    enabled_agents,
    task_from_message,
    wait_task,
)


def _step(kind="implementation", *, required_capabilities=None, depends_on=None):
    return {
        "kind": kind,
        "objective": f"{kind} objective from real orchestrator TurnDecision",
        "required_capabilities": required_capabilities or [],
        "depends_on": depends_on or [],
        "expected_output": {"kind": kind},
    }


def _turn_decision(decision_type="plan_task", **overrides):
    decision = {
        "decision_type": decision_type,
        "target_type": "orchestrator",
        "target_source": "auto_orchestrate",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": "Create a durable orchestrator plan",
        "steps": [_step("implementation", required_capabilities=["code"])],
        "reason": "structured router decision fixture",
        "confidence": "high",
        "clarification_question": None,
    }
    decision.update(overrides)
    return decision


def _post_turn_message(api_request, conversation_id, decision, *, expected={200, 201}, mentions=None):
    body = {
        "message_type": "text",
        "content": {"text": "The product path must follow structured router output."},
        "turn_decision": decision,
    }
    if mentions is not None:
        body["mentions"] = mentions
    _, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation_id}/messages",
        body,
        expected=expected,
    )
    return payload


def test_real_orchestrator_router_not_configured_returns_error_without_task(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} real planner not configured")

    _, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "Force router without a supplied structured decision."},
            "turn_route": True,
        },
        expected=503,
    )

    assert payload["error_code"] == "turn_router_not_configured"
    assert conversation_tasks(api_request, conversation["id"]) == []


def test_real_orchestrator_valid_plan_task_creates_task_plan_steps(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} real planner plan")

    message = _post_turn_message(
        api_request,
        conversation["id"],
        _turn_decision(
            steps=[
                _step("analysis"),
                _step("implementation", required_capabilities=["code"], depends_on=["step-1"]),
                _step("review", required_capabilities=["review"], depends_on=["step-2"]),
            ]
        ),
    )
    task = wait_task(api_request, task_from_message(message), terminal=("planned",))

    assert task["status"] == "planned"
    assert task["plan"]["status"] == "ready"
    assert [step["kind"] for step in task["steps"]] == ["analysis", "implementation", "review"]
    assert task["steps"][1]["depends_on"] == [task["steps"][0]["id"]]
    assert task["steps"][2]["depends_on"] == [task["steps"][1]["id"]]
    assert all(step["dispatch_source"] in {"capability", "blocked"} for step in task["steps"])
    assert_no_run_succeeded(task)


def test_real_orchestrator_invalid_turn_output_creates_no_task(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} real planner invalid output")

    _, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "Invalid structured router output must stop planning."},
            "turn_decision": _turn_decision(steps=[]),
        },
        expected=400,
    )

    assert payload["error_code"] == "turn_router_invalid_output"
    assert conversation_tasks(api_request, conversation["id"]) == []


def test_real_orchestrator_no_action_creates_only_message(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} real planner no action")

    message = _post_turn_message(
        api_request,
        conversation["id"],
        _turn_decision(
            "no_action",
            target_type="none",
            target_source="none",
            goal=None,
            steps=[],
        ),
    )

    assert "task_id" not in message
    assert "run_id" not in message
    assert conversation_tasks(api_request, conversation["id"]) == []
    assert len(conversation_messages(api_request, conversation["id"])) == 1


def test_real_orchestrator_needs_clarification_writes_assistant_message(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} real planner clarification")

    message = _post_turn_message(
        api_request,
        conversation["id"],
        _turn_decision(
            "needs_clarification",
            goal=None,
            steps=[],
            clarification_question="Which repository should the plan target?",
        ),
    )

    clarification = message["clarification_message"]
    assert clarification["sender_type"] == "assistant"
    assert clarification["sender_id"] == "orchestrator"
    assert clarification["reply_to_id"] == message["id"]
    assert clarification["created_by_run_id"] is None
    assert conversation_tasks(api_request, conversation["id"]) == []
    assert len(conversation_messages(api_request, conversation["id"])) == 2


def test_real_orchestrator_direct_response_creates_agentrun_or_explicit_error(api_request, unique_id):
    agent = enabled_agents(api_request, minimum=1)[0]
    conversation = create_conversation(
        api_request,
        f"{unique_id} real planner direct response",
        mode="private_agent",
        agent_ids=[agent["id"]],
    )

    message = _post_turn_message(
        api_request,
        conversation["id"],
        _turn_decision(
            "direct_response",
            target_type="agent",
            target_source="private_chat",
            target_agent_id=agent["id"],
            target_agent_ids=[agent["id"]],
            goal=None,
            steps=[],
        ),
        expected={201, 503},
    )

    if message.get("error_code") == "direct_response_not_available":
        assert conversation_tasks(api_request, conversation["id"]) == []
        return
    assert message["run_id"]
    assert message["agent_run"]["run_mode"] == "direct_response"
    assert message["agent_run"]["status"] in {"failed", "succeeded"}
    assert conversation_tasks(api_request, conversation["id"]) == []


def test_real_orchestrator_no_matching_capability_creates_blocked_step(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} real planner blocked")

    message = _post_turn_message(
        api_request,
        conversation["id"],
        _turn_decision(steps=[_step("analysis", required_capabilities=["nonexistent-capability"])]),
    )
    task = wait_task(api_request, task_from_message(message), terminal=("planned",))
    step = task["steps"][0]

    assert step["status"] == "blocked"
    assert step["dispatch_source"] == "blocked"
    assert step["blocked_reason"] == "no_capability_match"
    assert step["assigned_agent_id"] is None


def test_real_orchestrator_mentions_do_not_invoke_turn_router(api_request, unique_id):
    agent = enabled_agents(api_request, minimum=1)[0]
    conversation = create_conversation(
        api_request,
        f"{unique_id} real planner mention bypass",
        mode="group_agent",
        agent_ids=[agent["id"]],
    )

    message = _post_turn_message(
        api_request,
        conversation["id"],
        _turn_decision(
            "direct_response",
            target_type="agent",
            target_source="mention",
            target_agent_id=agent["id"],
            target_agent_ids=[agent["id"]],
            goal=None,
            steps=[],
            answer="This unsupported field would fail if the router were invoked.",
        ),
        mentions=[{"agent_id": agent["id"], "display": agent["name"]}],
    )
    task = wait_task(api_request, task_from_message(message), terminal=("planned",))
    step = task["steps"][0]

    assert step["assigned_agent_id"] == agent["id"]
    assert step["dispatch_source"] == "mention"
    assert "explicit_mention" in step["dispatch_reason"]
