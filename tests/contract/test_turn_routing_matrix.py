from tests.support import (
    assert_no_run_succeeded,
    conversation_tasks,
    create_conversation,
    enabled_agents,
    task_from_message,
    wait_task,
)

from services.api.app.orchestration.turn_schema import validate_turn_decision


def _step(kind="implementation", *, required_capabilities=None, depends_on=None):
    return {
        "kind": kind,
        "objective": f"{kind} objective from TurnDecision",
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
        "goal": "Persist a TurnDecision plan task",
        "steps": [_step("implementation", required_capabilities=["code"])],
        "reason": "contract injected TurnDecision",
        "confidence": "high",
        "clarification_question": None,
    }
    decision.update(overrides)
    return decision


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


def test_turn_routing_matrix_schema_covers_private_group_and_mention_paths():
    scenarios = [
        _turn_decision(
            "direct_response",
            target_type="agent",
            target_source="private_chat",
            target_agent_id="agent-a",
            target_agent_ids=["agent-a"],
            goal=None,
            steps=[],
        ),
        _turn_decision(
            "plan_task",
            target_type="agent",
            target_source="private_chat",
            target_agent_id="agent-a",
            target_agent_ids=["agent-a"],
        ),
        _turn_decision("direct_response", goal=None, steps=[]),
        _turn_decision(),
        _turn_decision(
            "direct_response",
            target_type="agent",
            target_source="mention",
            target_agent_id="agent-a",
            target_agent_ids=["agent-a"],
            goal=None,
            steps=[],
        ),
        _turn_decision(
            "plan_task",
            target_type="agent",
            target_source="mention",
            target_agent_id="agent-a",
            target_agent_ids=["agent-a"],
        ),
        _turn_decision(
            "no_action",
            target_type="none",
            target_source="none",
            goal=None,
            steps=[],
        ),
        _turn_decision("direct_response", goal=None, steps=[]),
        _turn_decision(),
    ]

    assert [validate_turn_decision(item).decision_type for item in scenarios] == [
        "direct_response",
        "plan_task",
        "direct_response",
        "plan_task",
        "direct_response",
        "plan_task",
        "no_action",
        "direct_response",
        "plan_task",
    ]


def test_turn_decision_no_action_creates_no_task(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} turn no action")

    message = _post_turn_message(
        api_request,
        conversation["id"],
        "This text is not classified by product code.",
        _turn_decision(
            "no_action",
            target_type="none",
            target_source="none",
            goal=None,
            steps=[],
        ),
    )

    assert "task_id" not in message
    assert conversation_tasks(api_request, conversation["id"]) == []


def test_turn_decision_plan_task_reuses_a6_plan_path(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} turn plan task")

    message = _post_turn_message(
        api_request,
        conversation["id"],
        "Only the injected TurnDecision should create a plan.",
        _turn_decision(
            steps=[
                _step("implementation", required_capabilities=["code"]),
                _step("review", required_capabilities=["review"], depends_on=["step-1"]),
            ]
        ),
    )
    task = wait_task(api_request, task_from_message(message), terminal=("planned",))
    steps = task["steps"]

    assert task["status"] == "planned"
    assert task["plan"]["status"] == "ready"
    assert [step["kind"] for step in steps] == ["implementation", "review"]
    assert steps[1]["depends_on"] == [steps[0]["id"]]
    assert all(step["dispatch_source"] in {"capability", "blocked"} for step in steps)
    assert_no_run_succeeded(task)


def test_turn_decision_direct_response_creates_failed_agent_run(api_request, unique_id):
    agent = enabled_agents(api_request, minimum=1)[0]
    conversation = create_conversation(
        api_request,
        f"{unique_id} turn direct creates run",
        mode="private_agent",
        agent_ids=[agent["id"]],
    )

    _, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "A direct response creates a failed run when the provider is not configured."},
            "turn_decision": _turn_decision(
                "direct_response",
                target_type="agent",
                target_source="private_chat",
                target_agent_id=agent["id"],
                target_agent_ids=[agent["id"]],
                goal=None,
                steps=[],
            ),
        },
        expected=201,
    )

    assert payload["run_id"]
    assert payload["agent_run"]["status"] == "failed"
    assert payload["agent_run"]["error_code"] == "provider_not_configured"
    assert conversation_tasks(api_request, conversation["id"]) == []
    assert_no_run_succeeded(payload)


def test_turn_decision_needs_clarification_creates_assistant_message_without_task(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} turn clarification unavailable")

    _, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "A clarification path is explicit, not a fake answer."},
            "turn_decision": _turn_decision(
                "needs_clarification",
                goal=None,
                steps=[],
                clarification_question="Which scope should be planned first?",
            ),
        },
        expected=201,
    )

    clarification = payload["clarification_message"]
    assert clarification["sender_type"] == "assistant"
    assert clarification["sender_id"] == "orchestrator"
    assert clarification["reply_to_id"] == payload["id"]
    assert clarification["created_by_run_id"] is None
    assert clarification["content"]["text"] == "Which scope should be planned first?"
    assert conversation_tasks(api_request, conversation["id"]) == []
    assert_no_run_succeeded(payload)


def test_mentions_bypass_turn_router_and_keep_a5_behavior(api_request, unique_id):
    target_agent = enabled_agents(api_request, minimum=1)[0]
    conversation = create_conversation(
        api_request,
        f"{unique_id} turn mention bypass",
        mode="group_agent",
        agent_ids=[target_agent["id"]],
    )

    _, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": f"@{target_agent['name']} keep A5 dispatch"},
            "mentions": [{"agent_id": target_agent["id"], "display": target_agent["name"]}],
            "turn_decision": _turn_decision(
                "direct_response",
                target_type="agent",
                target_source="mention",
                target_agent_id=target_agent["id"],
                target_agent_ids=[target_agent["id"]],
                goal=None,
                steps=[],
                answer="This invalid router field must be ignored by A5.",
            ),
        },
        expected={200, 201},
    )
    task = wait_task(api_request, task_from_message(payload), terminal=("planned",))
    step = task["steps"][0]

    assert step["assigned_agent_id"] == target_agent["id"]
    assert step["dispatch_source"] == "mention"
    assert "explicit_mention" in step["dispatch_reason"]
    assert_no_run_succeeded(task)
