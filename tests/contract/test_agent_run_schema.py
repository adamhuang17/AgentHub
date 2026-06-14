import pytest

from services.api.app.agent_runs.schema import validate_agent_run_request
from services.api.app.shared.errors import ValidationError


def _request(**overrides):
    payload = {
        "run_id": "run-contract",
        "conversation_id": "conv-contract",
        "source_type": "message",
        "source_message_id": "msg-contract",
        "plan_step_id": None,
        "target_agent_id": "agent-contract",
        "run_mode": "direct_response",
        "instruction": "Answer without leaking adapter-specific fields.",
        "context_bundle": {"recent_messages": []},
        "workspace_ref": None,
        "allowed_tools": [],
        "expected_artifacts": [],
    }
    payload.update(overrides)
    return payload


def test_agent_run_request_accepts_direct_response_message_source():
    request = validate_agent_run_request(_request())

    assert request.source_type == "message"
    assert request.run_mode == "direct_response"
    assert request.source_message_id == "msg-contract"
    assert request.plan_step_id is None


def test_agent_run_request_accepts_planned_step_source():
    request = validate_agent_run_request(
        _request(
            source_type="plan_step",
            source_message_id=None,
            plan_step_id="step-contract",
            run_mode="planned_step",
        )
    )

    assert request.source_type == "plan_step"
    assert request.run_mode == "planned_step"
    assert request.plan_step_id == "step-contract"


def test_agent_run_request_rejects_invalid_source_pairings():
    with pytest.raises(ValidationError, match="source_type=message requires run_mode=direct_response"):
        validate_agent_run_request(_request(run_mode="planned_step"))

    with pytest.raises(ValidationError, match="source_type=plan_step requires plan_step_id"):
        validate_agent_run_request(
            _request(source_type="plan_step", source_message_id=None, plan_step_id=None, run_mode="planned_step")
        )

