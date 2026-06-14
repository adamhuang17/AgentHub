from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.api.app.shared.errors import ValidationError


DEPLOYMENT_RELEASE_STATUSES = {"created", "publishing", "published", "failed"}
DEPLOYMENT_ERROR_CODES = {
    "deployment_failed",
    "deployment_artifact_unsupported",
    "deployment_artifact_checksum_mismatch",
    "deployment_provider_not_configured",
    "deployment_credentials_missing",
    "deployment_provider_failed",
    "deployment_publish_failed",
}
DEPLOYABLE_ARTIFACT_TYPES = {"web_preview", "web_app", "static_site"}
DEFAULT_DEPLOYMENT_PROVIDER = "disabled"


@dataclass(frozen=True)
class DeploymentRelease:
    id: str
    artifact_id: str
    artifact_version_id: str
    provider: str
    status: str
    url: str | None
    error_code: str | None
    created_at: str
    published_at: str | None


def validate_deploy_request(raw: dict[str, Any]) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ValidationError("Deployment request must be an object.", code="deployment_request_invalid")
    return {
        "provider": _optional_string(raw.get("provider"), "provider") or DEFAULT_DEPLOYMENT_PROVIDER,
    }


def validate_deployment_release(raw: dict[str, Any]) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ValidationError("DeploymentRelease must be an object.", code="deployment_release_invalid")

    release = {
        "id": _required_string(raw, "id"),
        "artifact_id": _required_string(raw, "artifact_id"),
        "artifact_version_id": _required_string(raw, "artifact_version_id"),
        "provider": _required_string(raw, "provider"),
        "status": _enum(raw.get("status"), "status", DEPLOYMENT_RELEASE_STATUSES),
        "url": _optional_string(raw.get("url"), "url"),
        "error_code": _optional_string(raw.get("error_code"), "error_code"),
        "created_at": _required_string(raw, "created_at"),
        "published_at": _optional_string(raw.get("published_at"), "published_at"),
    }
    _validate_terminal_fields(release)
    return release


def deployment_release_to_response(release: dict[str, object]) -> dict[str, object]:
    payload = validate_deployment_release(release)
    return {
        "id": payload["id"],
        "artifact_id": payload["artifact_id"],
        "artifact_version_id": payload["artifact_version_id"],
        "provider": payload["provider"],
        "status": payload["status"],
        "url": payload["url"],
        "error_code": payload["error_code"],
        "created_at": payload["created_at"],
        "published_at": payload["published_at"],
    }


def _validate_terminal_fields(release: dict[str, object]) -> None:
    status = release["status"]
    url = release["url"]
    error_code = release["error_code"]
    published_at = release["published_at"]
    if status == "published":
        if not isinstance(url, str) or not url:
            raise ValidationError("Published DeploymentRelease must include a URL.", code="deployment_release_invalid")
        if error_code is not None:
            raise ValidationError(
                "Published DeploymentRelease must not include an error code.",
                code="deployment_release_invalid",
            )
        if published_at is None:
            raise ValidationError(
                "Published DeploymentRelease must include published_at.",
                code="deployment_release_invalid",
            )
        return
    if status == "failed" and url is not None:
        raise ValidationError("Failed DeploymentRelease must not include a URL.", code="deployment_release_invalid")


def _required_string(raw: dict[str, Any], field: str) -> str:
    return _required_string_value(raw.get(field), field)


def _required_string_value(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.", code="deployment_release_invalid")
    return value.strip()


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_string_value(value, field)


def _enum(value: object, field: str, allowed: set[str]) -> str:
    clean = _required_string_value(value, field)
    if clean not in allowed:
        raise ValidationError(f"Unsupported {field}: {clean}", code="deployment_release_invalid")
    return clean
