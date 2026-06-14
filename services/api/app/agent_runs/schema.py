from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.api.app.shared.errors import ValidationError


SOURCE_TYPES = {"message", "plan_step"}
RUN_MODES = {"direct_response", "planned_step"}
RUN_STATUSES = {"created", "running", "failed", "succeeded", "cancelled", "incomplete", "final_content_empty"}
EVENT_TYPES = {
    "run_created",
    "run_started",
    "adapter_preflight_started",
    "adapter_preflight_succeeded",
    "adapter_preflight_failed",
    "adapter_process_started",
    "adapter_error",
    "provider_not_configured",
    "backend_session_started",
    "backend_retry",
    "assistant_message_delta",
    "assistant_message_completed",
    "artifact_created",
    "stdout_line",
    "stderr_line",
    "raw_backend_event",
    "usage_reported",
    "run_timed_out",
    "run_failed",
    "run_succeeded",
}


@dataclass(frozen=True)
class AgentRunRequest:
    run_id: str
    conversation_id: str
    source_type: str
    source_message_id: str | None
    plan_step_id: str | None
    target_agent_id: str
    run_mode: str
    instruction: str
    context_bundle: dict[str, object]
    workspace_ref: dict[str, object] | None
    allowed_tools: list[str]
    expected_artifacts: list[dict[str, object]]


@dataclass(frozen=True)
class AgentRunEventDraft:
    type: str
    payload: dict[str, object]


def validate_agent_run_request(raw: dict[str, Any]) -> AgentRunRequest:
    if not isinstance(raw, dict):
        raise ValidationError("AgentRunRequest must be an object.")

    request = AgentRunRequest(
        run_id=_required_string(raw, "run_id"),
        conversation_id=_required_string(raw, "conversation_id"),
        source_type=_enum(raw, "source_type", SOURCE_TYPES),
        source_message_id=_optional_string(raw, "source_message_id"),
        plan_step_id=_optional_string(raw, "plan_step_id"),
        target_agent_id=_required_string(raw, "target_agent_id"),
        run_mode=_enum(raw, "run_mode", RUN_MODES),
        instruction=_required_string(raw, "instruction"),
        context_bundle=_object(raw.get("context_bundle"), "context_bundle"),
        workspace_ref=_optional_object(raw.get("workspace_ref"), "workspace_ref"),
        allowed_tools=_string_list(raw.get("allowed_tools"), "allowed_tools"),
        expected_artifacts=_object_list(raw.get("expected_artifacts"), "expected_artifacts"),
    )
    validate_source_pairing(
        source_type=request.source_type,
        run_mode=request.run_mode,
        source_message_id=request.source_message_id,
        plan_step_id=request.plan_step_id,
    )
    return request


def validate_source_pairing(
    *,
    source_type: str,
    run_mode: str,
    source_message_id: str | None,
    plan_step_id: str | None,
) -> None:
    if source_type == "message":
        if run_mode != "direct_response":
            raise ValidationError("source_type=message requires run_mode=direct_response.")
        if not source_message_id:
            raise ValidationError("source_type=message requires source_message_id.")
        if plan_step_id is not None:
            raise ValidationError("source_type=message requires plan_step_id to be null.")
        return

    if source_type == "plan_step":
        if run_mode != "planned_step":
            raise ValidationError("source_type=plan_step requires run_mode=planned_step.")
        if not plan_step_id:
            raise ValidationError("source_type=plan_step requires plan_step_id.")
        return

    raise ValidationError(f"Unsupported source_type: {source_type}")


def validate_event_type(event_type: str) -> None:
    if event_type not in EVENT_TYPES:
        raise ValidationError(f"Unsupported agent run event type: {event_type}")


def run_to_response(run: dict[str, object]) -> dict[str, object]:
    response = dict(run)
    response["run_id"] = response["id"]
    return response


def _required_string(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.")
    return value


def _optional_string(raw: dict[str, Any], field: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string when provided.")
    return value


def _enum(raw: dict[str, Any], field: str, allowed: set[str]) -> str:
    value = _required_string(raw, field)
    if value not in allowed:
        raise ValidationError(f"Unsupported {field}: {value}")
    return value


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError(f"{field} must be an object.")
    return dict(value)


def _optional_object(value: object, field: str) -> dict[str, object] | None:
    if value is None:
        return None
    return _object(value, field)


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError(f"{field} must contain non-empty strings.")
    return list(value)


def _object_list(value: object, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list.")
    if any(not isinstance(item, dict) for item in value):
        raise ValidationError(f"{field} must contain objects.")
    return [dict(item) for item in value]
