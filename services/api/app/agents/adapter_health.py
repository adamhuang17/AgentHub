from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.api.app.shared.errors import ValidationError
from services.api.app.shared.time import utc_now


ADAPTER_HEALTH_STATUSES = {
    "ready",
    "not_configured",
    "missing_credentials",
    "unsupported_provider",
    "unavailable",
}


@dataclass(frozen=True)
class AdapterHealth:
    provider: str | None
    adapter_kind: str
    configured: bool
    status: str
    error_code: str | None
    recovery_hint: str | None
    checked_at: str
    capabilities: list[str]
    message: str | None = None


def validate_adapter_health(raw: dict[str, Any]) -> AdapterHealth:
    status = _required_string(raw, "status")
    if status not in ADAPTER_HEALTH_STATUSES:
        raise ValidationError(f"Unsupported adapter health status: {status}", code="adapter_health_invalid_status")

    configured = raw.get("configured")
    if not isinstance(configured, bool):
        raise ValidationError("configured must be a boolean.", code="adapter_health_invalid_configured")

    provider = _optional_string(raw.get("provider"), "provider")
    adapter_kind = _required_string(raw, "adapter_kind")
    error_code = _optional_string(raw.get("error_code"), "error_code")
    recovery_hint = _optional_string(raw.get("recovery_hint"), "recovery_hint")
    checked_at = _required_string(raw, "checked_at")
    message = _optional_string(raw.get("message"), "message")
    capabilities = _string_list(raw.get("capabilities"), "capabilities")

    return AdapterHealth(
        provider=provider,
        adapter_kind=adapter_kind,
        configured=configured,
        status=status,
        error_code=error_code,
        recovery_hint=recovery_hint,
        checked_at=checked_at,
        capabilities=capabilities,
        message=message,
    )


def adapter_health_to_response(health: AdapterHealth) -> dict[str, object]:
    payload: dict[str, object] = {
        "provider": health.provider,
        "adapter_kind": health.adapter_kind,
        "configured": health.configured,
        "status": health.status,
        "error_code": health.error_code,
        "recovery_hint": health.recovery_hint,
        "checked_at": health.checked_at,
        "capabilities": list(health.capabilities),
    }
    if health.message is not None:
        payload["message"] = health.message
    return payload


def adapter_health(
    *,
    provider: str | None,
    adapter_kind: str,
    configured: bool,
    status: str,
    error_code: str | None,
    recovery_hint: str | None,
    capabilities: list[str] | None = None,
    message: str | None = None,
) -> AdapterHealth:
    return validate_adapter_health(
        {
            "provider": provider,
            "adapter_kind": adapter_kind,
            "configured": configured,
            "status": status,
            "error_code": error_code,
            "recovery_hint": recovery_hint,
            "checked_at": utc_now(),
            "capabilities": capabilities or [],
            "message": message,
        }
    )


def _required_string(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.", code="adapter_health_invalid")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string when provided.", code="adapter_health_invalid")
    return value


def _string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list.", code="adapter_health_invalid")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(f"{field} must contain non-empty strings.", code="adapter_health_invalid")
        result.append(item)
    return result
