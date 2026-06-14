from tests.support import (
    assert_no_run_succeeded,
    conversation_messages,
    conversation_tasks,
    create_conversation,
    create_disabled_agent_profile,
    enabled_agents,
    post_message,
    task_from_message,
    wait_task,
)


def _plan_steps(task):
    plan = task.get("plan") or {}
    steps = plan.get("steps") or task.get("steps") or []
    assert plan, f"Mentioned task must include a plan: {task}"
    assert steps, f"Mentioned task must create plan steps: {task}"
    return plan, steps


def _assert_no_run_success_payload(*payloads):
    for payload in payloads:
        assert_no_run_succeeded(payload)
        plan = payload.get("plan") if isinstance(payload, dict) else None
        if isinstance(payload, dict):
            assert "runs" not in payload, payload
            assert "events" not in payload, payload
        if isinstance(plan, dict):
            assert "runs" not in plan, plan
            assert "events" not in plan, plan
        steps = []
        if isinstance(payload, dict):
            steps = payload.get("steps") or []
            if isinstance(plan, dict):
                steps = list(steps) + list(plan.get("steps") or [])
        for step in steps:
            assert "run_id" not in step, step
            assert step.get("run_status") != "succeeded", step


def _assert_mention_step(step, agent_id):
    assert step["assigned_agent_id"] == agent_id
    assert step["status"] == "assigned"
    assert step["dispatch_source"] == "mention"
    assert step["dispatch_reason"], step
    assert "explicit_mention" in step["dispatch_reason"], step
    assert "run_id" not in step, step
    assert step.get("run_status") != "succeeded", step


def test_a5_mention_dispatch(api_request, unique_id):
    target_agent = enabled_agents(api_request, minimum=1)[0]
    conversation = create_conversation(
        api_request,
        f"{unique_id} mention dispatch",
        mode="group_agent",
        agent_ids=[target_agent["id"]],
    )

    message = post_message(
        api_request,
        conversation["id"],
        f"@{target_agent['name']} inspect this request and respond through the task pipeline",
        mentions=[{"agent_id": target_agent["id"], "display": target_agent["name"]}],
    )
    task = wait_task(api_request, task_from_message(message), terminal=("planned",))
    assert task["status"] == "planned"
    assert_no_run_succeeded(message)

    plan, steps = _plan_steps(task)
    assert plan["status"] == "ready"
    assert len(steps) == 1
    _assert_mention_step(steps[0], target_agent["id"])
    _assert_no_run_success_payload(message, task, plan)


def test_a5_multi_mention_dispatches_each_mentioned_agent(api_request, unique_id):
    agents = enabled_agents(api_request, minimum=2)[:2]
    mentioned_ids = {agent["id"] for agent in agents}
    conversation = create_conversation(
        api_request,
        f"{unique_id} multi mention dispatch",
        mode="group_agent",
        agent_ids=[agent["id"] for agent in agents],
    )

    message = post_message(
        api_request,
        conversation["id"],
        " ".join(f"@{agent['name']}" for agent in agents) + " divide this request between the mentioned agents",
        mentions=[{"agent_id": agent["id"], "display": agent["name"]} for agent in agents],
    )
    task = wait_task(api_request, task_from_message(message), terminal=("planned",))
    assert task["status"] == "planned"

    plan, steps = _plan_steps(task)
    assigned_ids = {step["assigned_agent_id"] for step in steps}
    assert plan["status"] == "ready"
    assert len(steps) == len(mentioned_ids)
    assert assigned_ids == mentioned_ids
    for step in steps:
        _assert_mention_step(step, step["assigned_agent_id"])
    _assert_no_run_success_payload(message, task, plan)


def test_a5_unknown_mentioned_agent_rejected_without_partial_dispatch(api_request, unique_id):
    conversation = create_conversation(api_request, f"{unique_id} unknown mention dispatch")
    missing_agent_id = f"{unique_id}-missing-agent"

    status, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": "@MissingAgent should fail without fallback"},
            "mentions": [{"agent_id": missing_agent_id, "display": "MissingAgent"}],
        },
        expected={400, 422},
    )

    assert status in {400, 422}
    assert payload["code"] == "unknown_agent"
    assert missing_agent_id in payload["message"]
    assert "task_id" not in payload
    assert "created_task_id" not in payload
    assert conversation_messages(api_request, conversation["id"]) == []
    assert conversation_tasks(api_request, conversation["id"]) == []
    _assert_no_run_success_payload(payload)


def test_a5_disabled_mentioned_agent_rejected_without_partial_dispatch(api_request, unique_id):
    disabled_agent = create_disabled_agent_profile(unique_id)
    conversation = create_conversation(api_request, f"{unique_id} disabled mention dispatch")

    status, payload, _ = api_request(
        "POST",
        f"/api/conversations/{conversation['id']}/messages",
        {
            "message_type": "text",
            "content": {"text": f"@{disabled_agent['name']} should not receive work"},
            "mentions": [{"agent_id": disabled_agent["id"], "display": disabled_agent["name"]}],
        },
        expected={400, 422},
    )

    assert status in {400, 422}
    assert payload["code"] == "agent_disabled"
    assert disabled_agent["id"] in payload["message"]
    assert "task_id" not in payload
    assert "created_task_id" not in payload
    assert conversation_messages(api_request, conversation["id"]) == []
    assert conversation_tasks(api_request, conversation["id"]) == []
    _assert_no_run_success_payload(payload)
