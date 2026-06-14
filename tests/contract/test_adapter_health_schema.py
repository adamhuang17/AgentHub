import pytest

from services.api.app.agents.adapter_health import (
    ADAPTER_HEALTH_STATUSES,
    adapter_health,
    adapter_health_to_response,
    validate_adapter_health,
)
from services.api.app.agents.adapters.disabled import DisabledAdapter
from services.api.app.shared.errors import ValidationError


def test_adapter_health_schema_validates_allowed_statuses():
    for status in ADAPTER_HEALTH_STATUSES:
        health = adapter_health(
            provider="codex",
            adapter_kind="codex",
            configured=status == "ready",
            status=status,
            error_code=None if status == "ready" else "provider_not_configured",
            recovery_hint=None if status == "ready" else "Configure provider credentials.",
            capabilities=["code"] if status == "ready" else [],
        )
        payload = adapter_health_to_response(health)

        assert payload["status"] == status
        assert payload["adapter_kind"] == "codex"
        assert "checked_at" in payload
        assert isinstance(payload["capabilities"], list)


def test_adapter_health_schema_rejects_unknown_status():
    with pytest.raises(ValidationError) as exc_info:
        validate_adapter_health(
            {
                "provider": "codex",
                "adapter_kind": "codex",
                "configured": False,
                "status": "healthy",
                "error_code": "provider_not_configured",
                "recovery_hint": "Use the A7 readiness status enum.",
                "checked_at": "2026-06-10T00:00:00.000000Z",
                "capabilities": [],
            }
        )

    assert exc_info.value.code == "adapter_health_invalid_status"


def test_disabled_adapter_health_returns_provider_not_configured():
    health = DisabledAdapter(provider="codex", target_agent_id="agent-contract").health()

    assert health.configured is False
    assert health.status == "not_configured"
    assert health.error_code == "provider_not_configured"
    assert health.provider == "codex"
    assert health.adapter_kind == "disabled"
    assert health.recovery_hint
    assert health.capabilities == []
