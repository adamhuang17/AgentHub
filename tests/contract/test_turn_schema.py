import pytest

from services.api.app.orchestration.turn_schema import (
    TurnSchemaError,
    normalize_turn_decision_defaults,
    validate_turn_decision,
)


def _step(kind="implementation", depends_on=None):
    return {
        "kind": kind,
        "objective": f"{kind} objective",
        "required_capabilities": ["code"] if kind == "implementation" else [],
        "depends_on": depends_on or [],
        "expected_output": {"kind": kind},
    }


def _decision(decision_type="plan_task", **overrides):
    decision = {
        "decision_type": decision_type,
        "target_type": "orchestrator",
        "target_source": "auto_orchestrate",
        "target_agent_id": None,
        "target_agent_ids": [],
        "goal": "Create a contract-level turn plan",
        "steps": [_step()],
        "reason": "contract fixture",
        "confidence": "high",
        "clarification_question": None,
    }
    decision.update(overrides)
    return decision


def test_turn_schema_rejects_answer_in_direct_response():
    decision = _decision(
        "direct_response",
        goal=None,
        steps=[],
        answer="This would be a fake assistant answer.",
    )

    with pytest.raises(TurnSchemaError, match="unsupported fields"):
        validate_turn_decision(decision)


def test_turn_schema_rejects_invalid_step_kind():
    decision = _decision(steps=[_step("deploy")])

    with pytest.raises(TurnSchemaError, match="Unsupported step kind: deploy"):
        validate_turn_decision(decision)


def test_no_action_shape_has_no_target_or_steps():
    decision = validate_turn_decision(
        _decision(
            "no_action",
            target_type="none",
            target_source="none",
            goal=None,
            steps=[],
        )
    )

    assert decision.decision_type == "no_action"
    assert decision.target_agent_ids == []
    assert decision.goal is None
    assert decision.steps == []


def test_direct_response_shape_has_target_but_no_plan():
    decision = validate_turn_decision(
        _decision(
            "direct_response",
            target_type="agent",
            target_source="mention",
            target_agent_id="agent-a",
            target_agent_ids=["agent-a"],
            goal=None,
            steps=[],
        )
    )

    assert decision.decision_type == "direct_response"
    assert decision.target_agent_ids == ["agent-a"]
    assert decision.steps == []


def test_direct_response_defaults_fill_private_agent_target():
    normalized = normalize_turn_decision_defaults(
        _decision(
            "direct_response",
            target_type="",
            target_source="none",
            target_agent_id=None,
            target_agent_ids=[],
            goal=None,
            steps=[],
        ),
        conversation_mode="private_agent",
        private_agent_id="agent-private",
    )
    decision = validate_turn_decision(normalized)

    assert decision.target_type == "agent"
    assert decision.target_source == "private_chat"
    assert decision.target_agent_id == "agent-private"
    assert decision.target_agent_ids == ["agent-private"]


def test_direct_response_defaults_fill_mention_target():
    normalized = normalize_turn_decision_defaults(
        _decision(
            "direct_response",
            target_type="",
            target_source="none",
            target_agent_id=None,
            target_agent_ids=[],
            goal=None,
            steps=[],
        ),
        conversation_mode="group_agent",
        mentioned_agent_ids=["agent-mentioned"],
    )
    decision = validate_turn_decision(normalized)

    assert decision.target_type == "agent"
    assert decision.target_source == "mention"
    assert decision.target_agent_id == "agent-mentioned"
    assert decision.target_agent_ids == ["agent-mentioned"]


def test_plan_task_requires_one_to_three_steps():
    validate_turn_decision(_decision(steps=[_step("analysis"), _step("implementation", ["step-1"])]))

    with pytest.raises(TurnSchemaError, match="1-3"):
        validate_turn_decision(_decision(steps=[]))


def test_needs_clarification_requires_question_and_no_steps():
    decision = validate_turn_decision(
        _decision(
            "needs_clarification",
            goal=None,
            steps=[],
            clarification_question="Which API should be prioritized?",
        )
    )

    assert decision.decision_type == "needs_clarification"
    assert decision.clarification_question

    with pytest.raises(TurnSchemaError, match="clarification_question"):
        validate_turn_decision(_decision("needs_clarification", goal=None, steps=[]))
