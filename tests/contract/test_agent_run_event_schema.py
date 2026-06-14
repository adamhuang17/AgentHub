import pytest

from services.api.app.agent_runs.schema import EVENT_TYPES, validate_event_type
from services.api.app.shared.errors import ValidationError


def test_agent_run_event_schema_supports_a7_minimum_events():
    for event_type in {
        "run_created",
        "run_started",
        "adapter_error",
        "provider_not_configured",
        "run_failed",
        "run_succeeded",
    }:
        validate_event_type(event_type)


def test_agent_run_event_schema_keeps_assistant_events_enum_only_for_a7_1():
    assert "assistant_message_delta" in EVENT_TYPES
    assert "assistant_message_completed" in EVENT_TYPES


def test_agent_run_event_schema_supports_a7_3_real_adapter_events():
    for event_type in {
        "adapter_preflight_started",
        "adapter_preflight_succeeded",
        "adapter_preflight_failed",
        "adapter_process_started",
        "backend_session_started",
        "backend_retry",
        "stdout_line",
        "stderr_line",
        "raw_backend_event",
        "usage_reported",
        "run_timed_out",
    }:
        validate_event_type(event_type)


def test_agent_run_event_schema_rejects_unknown_event_type():
    with pytest.raises(ValidationError, match="Unsupported agent run event type"):
        validate_event_type("fake_success")
