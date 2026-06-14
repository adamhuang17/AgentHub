from __future__ import annotations

from http import HTTPStatus
from typing import Any

from services.api.app.preview.service import preview_artifact
from services.api.app.shared.errors import ValidationError
from services.api.app.shared.http import path_parts, single


RouteResponse = tuple[HTTPStatus, dict[str, object]]


def handle_get(path: str, query: dict[str, list[str]], test_run_id: str) -> RouteResponse | None:
    parts = path_parts(path)
    if len(parts) == 4 and parts[:2] == ["api", "artifacts"] and parts[3] == "preview":
        return HTTPStatus.OK, preview_artifact(
            parts[2],
            test_run_id=test_run_id,
            version=_optional_int(single(query, "version"), "version"),
            version_id=_optional_string(single(query, "version_id"), "version_id"),
        )
    return None


def handle_post(path: str, body: dict[str, Any], test_run_id: str) -> RouteResponse | None:
    parts = path_parts(path)
    if len(parts) == 4 and parts[:2] == ["api", "artifacts"] and parts[3] == "preview":
        return HTTPStatus.OK, preview_artifact(
            parts[2],
            test_run_id=test_run_id,
            version=_optional_int(body.get("version"), "version"),
            version_id=_optional_string(body.get("version_id"), "version_id"),
        )
    return None


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string when provided.", code="artifact_preview_invalid")
    return value.strip()


def _optional_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be an integer.", code="artifact_preview_invalid") from exc
    if parsed <= 0:
        raise ValidationError(f"{field} must be positive.", code="artifact_preview_invalid")
    return parsed
