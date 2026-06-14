from __future__ import annotations


PROVIDER_NOT_CONFIGURED = "provider_not_configured"


def provider_not_configured_payload(
    *,
    target_agent_id: str,
    provider: str | None,
) -> dict[str, object]:
    return {
        "error_code": PROVIDER_NOT_CONFIGURED,
        "message": "Agent provider is not configured for execution.",
        "provider": provider,
        "target_agent_id": target_agent_id,
        "recovery_hint": (
            "Configure provider credentials and model routing for this agent "
            "before starting a real run."
        ),
    }


def run_failed_payload(
    *,
    error_code: str,
    message: str,
    provider: str | None,
    target_agent_id: str,
    recovery_hint: str | None,
) -> dict[str, object]:
    return {
        "error_code": error_code,
        "message": message,
        "provider": provider,
        "target_agent_id": target_agent_id,
        "recovery_hint": recovery_hint,
    }


def adapter_error_payload(
    *,
    error_code: str,
    message: str,
    provider: str | None,
    target_agent_id: str | None,
    recovery_hint: str | None,
) -> dict[str, object]:
    return {
        "error_code": error_code,
        "message": message,
        "provider": provider,
        "target_agent_id": target_agent_id,
        "recovery_hint": recovery_hint,
    }
