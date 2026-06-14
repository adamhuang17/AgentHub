from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.api.app.shared.errors import ValidationError


ARTIFACT_STATUSES = {"available", "failed"}
DIFF_ARTIFACT_TYPES = {"diff_preview", "source_diff"}
PATCH_ARTIFACT_TYPES = {"patch", "diff_patch"}
DEPLOYMENT_RELEASE_ARTIFACT_TYPE = "deployment_release"
FORBIDDEN_ARTIFACT_TYPES = {
    "diff",
    "deployment",
    DEPLOYMENT_RELEASE_ARTIFACT_TYPE,
}
REVIEW_REQUEST_STATUSES = {"pending", "approved", "rejected"}
REVIEW_DECISIONS = {"approved", "rejected"}
PATCH_APPLICATION_STATUSES = {"review_required", "applied", "rejected", "failed", "conflict"}


@dataclass(frozen=True)
class Artifact:
    id: str
    conversation_id: str
    task_id: str | None
    created_by_run_id: str | None
    type: str
    title: str
    status: str
    mime_type: str
    storage_key: str
    created_at: str


@dataclass(frozen=True)
class ArtifactVersion:
    id: str
    artifact_id: str
    version: int
    storage_key: str
    checksum: str
    parent_version_id: str | None
    created_at: str


@dataclass(frozen=True)
class ReviewRequest:
    id: str
    conversation_id: str
    artifact_id: str
    action_type: str
    status: str
    payload_json: str
    created_at: str


@dataclass(frozen=True)
class ReviewDecision:
    id: str
    request_id: str
    decision: str
    decided_by: str
    comment: str | None
    created_at: str


@dataclass(frozen=True)
class PatchApplication:
    id: str
    patch_artifact_id: str | None
    diff_artifact_id: str | None
    target_artifact_id: str
    base_version_id: str
    result_version_id: str | None
    status: str
    error_code: str | None
    created_at: str


def validate_artifact_input(raw: dict[str, Any], *, allow_deployment_release: bool = False) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ValidationError("Artifact input must be an object.", code="artifact_invalid")

    artifact_type = _required_string(raw, "type")
    if artifact_type == DEPLOYMENT_RELEASE_ARTIFACT_TYPE and allow_deployment_release:
        pass
    elif artifact_type in FORBIDDEN_ARTIFACT_TYPES:
        raise ValidationError(
            f"Artifact type {artifact_type} is outside the A8 read-only artifact scope.",
            code="artifact_type_not_supported",
        )

    return {
        "conversation_id": _required_string(raw, "conversation_id"),
        "task_id": _optional_string(raw.get("task_id"), "task_id"),
        "created_by_run_id": _optional_string(raw.get("created_by_run_id"), "created_by_run_id"),
        "type": artifact_type,
        "title": _required_string(raw, "title"),
        "status": _enum(raw.get("status") or "available", "status", ARTIFACT_STATUSES),
        "mime_type": _required_string(raw, "mime_type"),
    }


def validate_diff_artifact_type(value: object | None) -> str:
    if value is None:
        return "diff_preview"
    artifact_type = _required_string_value(value, "type")
    if artifact_type not in DIFF_ARTIFACT_TYPES:
        raise ValidationError(
            "Diff artifacts must use type diff_preview or source_diff.",
            code="artifact_diff_type_not_supported",
        )
    return artifact_type


def validate_diff_request(raw: dict[str, Any]) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ValidationError("Diff request must be an object.", code="artifact_diff_invalid")

    return {
        "base_artifact_id": _required_string(raw, "base_artifact_id"),
        "base_version_id": _required_string(raw, "base_version_id"),
        "target_artifact_id": _required_string(raw, "target_artifact_id"),
        "target_version_id": _required_string(raw, "target_version_id"),
        "type": validate_diff_artifact_type(raw.get("type")),
        "title": _optional_string(raw.get("title"), "title"),
        "path": _optional_string(raw.get("path"), "path"),
        "base_checksum": _optional_string(raw.get("base_checksum"), "base_checksum"),
        "target_checksum": _optional_string(raw.get("target_checksum"), "target_checksum"),
    }


def validate_review_decision_input(raw: dict[str, Any]) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ValidationError("Review decision must be an object.", code="review_decision_invalid")

    return {
        "decision": _enum(raw.get("decision"), "decision", REVIEW_DECISIONS),
        "decided_by": _optional_string(raw.get("decided_by"), "decided_by") or "human",
        "comment": _optional_string(raw.get("comment"), "comment"),
    }


def artifact_to_response(artifact: dict[str, object]) -> dict[str, object]:
    version_id = artifact.get("current_version_id")
    response = dict(artifact)
    response["uri"] = f"artifact://{artifact['id']}"
    if version_id is not None:
        response["version_id"] = version_id
    return response


def artifact_version_to_response(version: dict[str, object]) -> dict[str, object]:
    response = dict(version)
    response["uri"] = f"artifact://{version['artifact_id']}/versions/{version['version']}"
    return response


def _required_string(raw: dict[str, Any], field: str) -> str:
    return _required_string_value(raw.get(field), field)


def _required_string_value(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.", code="artifact_invalid")
    return value.strip()


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_string_value(value, field)


def _enum(value: object, field: str, allowed: set[str]) -> str:
    clean = _required_string_value(value, field)
    if clean not in allowed:
        raise ValidationError(f"Unsupported {field}: {clean}", code="artifact_invalid")
    return clean
