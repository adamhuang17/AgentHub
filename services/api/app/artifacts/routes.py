from __future__ import annotations

from http import HTTPStatus
import inspect
from typing import Any
from urllib.parse import quote

from services.api.app.artifacts.diff_service import create_diff_artifact_from_request
from services.api.app.artifacts.patch_service import apply_patch_request
from services.api.app.artifacts.repository import (
    create_artifact,
    get_diff_artifact,
    get_artifact,
    list_artifact_versions,
    list_artifacts,
    read_artifact_download,
    read_artifact_content,
)
from services.api.app.artifacts.review_repository import (
    create_review_decision,
    list_review_requests,
)
from services.api.app.artifacts.schema import validate_review_decision_input
from services.api.app.shared.errors import ValidationError
from services.api.app.shared.http import path_parts, single


RouteResponse = tuple[HTTPStatus, dict[str, object]]


def handle_get(path: str, query: dict[str, list[str]], test_run_id: str) -> RouteResponse | None:
    parts = path_parts(path)
    if parts == ["api", "artifacts"]:
        return HTTPStatus.OK, {
            "items": list_artifacts(
                test_run_id=test_run_id,
                conversation_id=single(query, "conversation_id"),
                artifact_type=single(query, "type"),
                created_by_run_id=single(query, "created_by_run_id"),
            )
        }

    if parts == ["api", "review-requests"]:
        return HTTPStatus.OK, {
            "items": list_review_requests(
                test_run_id=test_run_id,
                conversation_id=single(query, "conversation_id"),
                status=single(query, "status"),
            )
        }

    if len(parts) == 3 and parts[:2] == ["api", "artifacts"]:
        return HTTPStatus.OK, get_artifact(parts[2], test_run_id=test_run_id)

    if len(parts) == 4 and parts[:2] == ["api", "artifacts"] and parts[3] == "versions":
        return HTTPStatus.OK, {"items": list_artifact_versions(parts[2], test_run_id=test_run_id)}

    if len(parts) == 4 and parts[:2] == ["api", "artifacts"] and parts[3] == "content":
        version = _optional_int(single(query, "version"), "version")
        return HTTPStatus.OK, read_artifact_content(parts[2], test_run_id=test_run_id, version=version)

    if len(parts) == 4 and parts[:2] == ["api", "artifacts"] and parts[3] == "download":
        version = _optional_int(single(query, "version"), "version")
        return _send_download_response(parts[2], test_run_id=test_run_id, version=version)

    if len(parts) == 4 and parts[:2] == ["api", "artifacts"] and parts[3] == "diff":
        return HTTPStatus.OK, get_diff_artifact(parts[2], test_run_id=test_run_id)

    return None


def handle_post(path: str, body: dict[str, Any], test_run_id: str) -> RouteResponse | None:
    if path_parts(path) == ["api", "artifacts", "diff"]:
        return HTTPStatus.CREATED, create_diff_artifact_from_request(body, test_run_id=test_run_id)

    parts = path_parts(path)
    if len(parts) == 4 and parts[:2] == ["api", "artifacts"] and parts[3] == "apply-patch":
        result = apply_patch_request(parts[2], body, test_run_id=test_run_id)
        return _apply_patch_status(result), result

    if len(parts) == 4 and parts[:2] == ["api", "review-requests"] and parts[3] == "decision":
        decision = validate_review_decision_input(body)
        return HTTPStatus.CREATED, create_review_decision(
            request_id=parts[2],
            decision=str(decision["decision"]),
            decided_by=str(decision["decided_by"]),
            comment=decision["comment"] if isinstance(decision["comment"], str) else None,
            test_run_id=test_run_id,
        )

    if parts != ["api", "artifacts"]:
        return None

    content = body.get("content")
    if not isinstance(content, str) or not content:
        raise ValidationError("content must be a non-empty string.", code="artifact_invalid_content")

    artifact = create_artifact(
        conversation_id=_required_string(body, "conversation_id"),
        artifact_type=_required_string(body, "type"),
        title=_required_string(body, "title"),
        mime_type=_required_string(body, "mime_type"),
        content=content,
        task_id=_optional_string(body.get("task_id"), "task_id"),
        created_by_run_id=_optional_string(body.get("created_by_run_id"), "created_by_run_id"),
        target_artifact_id=_optional_string(body.get("target_artifact_id"), "target_artifact_id"),
        base_version_id=_optional_string(body.get("base_version_id"), "base_version_id"),
        base_checksum=_optional_string(body.get("base_checksum"), "base_checksum"),
        test_run_id=test_run_id,
    )
    return HTTPStatus.CREATED, artifact


def _required_string(body: dict[str, Any], field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.", code="artifact_invalid")
    return value.strip()


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string when provided.", code="artifact_invalid")
    return value.strip()


def _optional_int(value: str | None, field: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValidationError(f"{field} must be an integer.", code="artifact_invalid") from exc
    if parsed <= 0:
        raise ValidationError(f"{field} must be positive.", code="artifact_invalid")
    return parsed


def _apply_patch_status(result: dict[str, object]) -> HTTPStatus:
    status = result.get("status")
    if status == "review_required":
        return HTTPStatus.ACCEPTED
    if status == "applied":
        return HTTPStatus.OK
    if status in {"rejected", "failed", "conflict"}:
        return HTTPStatus.CONFLICT
    return HTTPStatus.OK


def _send_download_response(
    artifact_id: str,
    *,
    test_run_id: str,
    version: int | None,
) -> RouteResponse:
    payload = read_artifact_download(artifact_id, test_run_id=test_run_id, version=version)
    handler = _current_request_handler()
    if handler is None:
        raise ValidationError(
            "Artifact download is only available within an HTTP request context.",
            code="artifact_download_unavailable",
        )

    body = payload["content"]
    if not isinstance(body, bytes):
        raise ValidationError("Artifact download payload must be bytes.", code="artifact_download_invalid")

    # The main API dispatcher only serializes JSON RouteResponse payloads, so
    # download responses are written directly for this request and then the
    # per-request JSON sender is suppressed.
    handler.send_response(HTTPStatus.OK.value)
    handler.send_header("Content-Type", str(payload["mime_type"]))
    handler.send_header("Content-Disposition", _content_disposition(str(payload["filename"])))
    handler.send_header("Content-Length", str(payload["content_length"]))
    handler.end_headers()
    handler.wfile.write(body)
    handler._send_route_response = lambda response: None
    return HTTPStatus.OK, {}


def _current_request_handler() -> Any | None:
    frame = inspect.currentframe()
    try:
        while frame is not None:
            candidate = frame.f_locals.get("self")
            if candidate is not None and hasattr(candidate, "send_response") and hasattr(candidate, "wfile"):
                return candidate
            frame = frame.f_back
    finally:
        del frame
    return None


def _content_disposition(filename: str) -> str:
    ascii_filename = filename.encode("ascii", errors="ignore").decode("ascii") or "artifact.bin"
    ascii_filename = ascii_filename.replace('"', "_")
    encoded_filename = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"
