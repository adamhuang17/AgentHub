from __future__ import annotations

import re
from typing import Any

from services.api.app.artifacts.repository import (
    append_artifact_version_with_patch_application,
    get_artifact,
    get_artifact_version_record,
    get_current_artifact_version_record,
    get_diff_artifact,
    read_artifact_content,
)
from services.api.app.artifacts.review_repository import (
    create_patch_application,
    create_review_request,
    get_review_request,
    latest_review_request_for_artifact,
    latest_patch_application_for_source,
)
from services.api.app.artifacts.schema import DIFF_ARTIFACT_TYPES, PATCH_ARTIFACT_TYPES
from services.api.app.artifacts.store import read_content
from services.api.app.shared.errors import NotFoundError, ValidationError


_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_MIME_TYPES = {
    "application/json",
    "application/javascript",
    "application/xml",
    "application/x-python-code",
    "application/vnd.agenthub.source+json",
}
_HUNK_RANGE_RE = re.compile(r"-([0-9]+)(?:,[0-9]+)?\s+\+([0-9]+)(?:,[0-9]+)?")


class PatchConflictError(Exception):
    pass


def apply_patch_request(patch_or_diff_artifact_id: str, raw: dict[str, Any], *, test_run_id: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ValidationError("Apply patch request must be an object.", code="artifact_apply_invalid")

    source = _patch_source(patch_or_diff_artifact_id, raw, test_run_id=test_run_id)
    review_request = _review_request_for_source(source, raw, test_run_id=test_run_id)
    if review_request["status"] == "pending":
        application = _existing_application(
            source,
            statuses={"review_required"},
            test_run_id=test_run_id,
        ) or _record_application(
            source,
            status="review_required",
            error_code="review_required",
            result_version_id=None,
            test_run_id=test_run_id,
        )
        application["review_request_id"] = review_request["id"]
        application["request_id"] = review_request["id"]
        return application

    if review_request["status"] == "rejected":
        application = _existing_application(
            source,
            statuses={"rejected"},
            test_run_id=test_run_id,
        ) or _record_application(
            source,
            status="rejected",
            error_code="review_rejected",
            result_version_id=None,
            test_run_id=test_run_id,
        )
        application["review_request_id"] = review_request["id"]
        application["request_id"] = review_request["id"]
        return application

    application = _apply_approved_patch(source, test_run_id=test_run_id)
    application["review_request_id"] = review_request["id"]
    application["request_id"] = review_request["id"]
    return application


def _patch_source(patch_or_diff_artifact_id: str, raw: dict[str, Any], *, test_run_id: str) -> dict[str, object]:
    artifact = get_artifact(patch_or_diff_artifact_id, test_run_id=test_run_id)
    artifact_type = str(artifact["type"])
    if artifact_type in DIFF_ARTIFACT_TYPES:
        return _diff_source(artifact, raw, test_run_id=test_run_id)
    if artifact_type in PATCH_ARTIFACT_TYPES:
        return _patch_artifact_source(artifact, raw, test_run_id=test_run_id)
    raise ValidationError("Artifact is not an applyable patch or diff artifact.", code="artifact_apply_not_supported")


def _patch_artifact_source(artifact: dict[str, object], raw: dict[str, Any], *, test_run_id: str) -> dict[str, object]:
    target_artifact_id = _optional_string(raw.get("target_artifact_id"), "target_artifact_id") or _optional_string(
        artifact.get("target_artifact_id"), "target_artifact_id"
    )
    if target_artifact_id is None:
        raise ValidationError("target_artifact_id is required for patch apply.", code="artifact_apply_invalid")

    target = get_artifact(target_artifact_id, test_run_id=test_run_id)
    if target["conversation_id"] != artifact["conversation_id"]:
        raise ValidationError("Patch target must belong to the same conversation.", code="artifact_apply_invalid")

    base_version_id = _optional_string(raw.get("base_version_id"), "base_version_id") or _optional_string(
        artifact.get("base_version_id"), "base_version_id"
    )
    if base_version_id is None:
        base_version_id = str(target["current_version_id"])
    _validate_base_version(target_artifact_id, base_version_id, test_run_id=test_run_id)
    content = read_artifact_content(str(artifact["id"]), test_run_id=test_run_id)
    return {
        "source_artifact_id": str(artifact["id"]),
        "patch_artifact_id": str(artifact["id"]),
        "diff_artifact_id": None,
        "conversation_id": str(artifact["conversation_id"]),
        "target_artifact_id": target_artifact_id,
        "base_version_id": base_version_id,
        "expected_base_checksum": _optional_string(raw.get("base_checksum"), "base_checksum")
        or _optional_string(artifact.get("base_checksum"), "base_checksum"),
        "patch_text": str(content["content"]),
    }


def _diff_source(artifact: dict[str, object], raw: dict[str, Any], *, test_run_id: str) -> dict[str, object]:
    diff = get_diff_artifact(str(artifact["id"]), test_run_id=test_run_id)
    target_artifact_id = _optional_string(raw.get("target_artifact_id"), "target_artifact_id") or str(
        diff["base_artifact_id"]
    )
    target = get_artifact(target_artifact_id, test_run_id=test_run_id)
    if target["conversation_id"] != artifact["conversation_id"]:
        raise ValidationError("Diff target must belong to the same conversation.", code="artifact_apply_invalid")
    files = diff.get("files")
    if not isinstance(files, list):
        raise ValidationError("Diff artifact has no applyable files.", code="artifact_apply_invalid_patch")
    unified_diffs = [str(file.get("unified_diff") or "") for file in files if isinstance(file, dict)]
    patch_text = "\n".join(part for part in unified_diffs if part)
    base_version_id = _optional_string(raw.get("base_version_id"), "base_version_id") or str(diff["base_version_id"])
    _validate_base_version(target_artifact_id, base_version_id, test_run_id=test_run_id)
    return {
        "source_artifact_id": str(artifact["id"]),
        "patch_artifact_id": None,
        "diff_artifact_id": str(artifact["id"]),
        "conversation_id": str(artifact["conversation_id"]),
        "target_artifact_id": target_artifact_id,
        "base_version_id": base_version_id,
        "expected_base_checksum": _optional_string(raw.get("base_checksum"), "base_checksum") or str(diff["base_checksum"]),
        "patch_text": patch_text,
    }


def _review_request_for_source(
    source: dict[str, object],
    raw: dict[str, Any],
    *,
    test_run_id: str,
) -> dict[str, object]:
    request_id = _optional_string(raw.get("review_request_id"), "review_request_id")
    if request_id is not None:
        request = get_review_request(request_id, test_run_id=test_run_id)
        _validate_review_request_matches(source, request)
        return request

    request = latest_review_request_for_artifact(str(source["source_artifact_id"]), test_run_id=test_run_id)
    if request is not None:
        _validate_review_request_matches(source, request)
        return request

    return create_review_request(
        conversation_id=str(source["conversation_id"]),
        artifact_id=str(source["source_artifact_id"]),
        payload=_review_payload(source),
        test_run_id=test_run_id,
    )


def _validate_base_version(target_artifact_id: str, base_version_id: str, *, test_run_id: str) -> None:
    try:
        get_artifact_version_record(target_artifact_id, base_version_id, test_run_id=test_run_id)
    except NotFoundError as exc:
        raise ValidationError(
            "base_version_id must reference the target artifact.",
            code="artifact_apply_base_version_invalid",
        ) from exc


def _validate_review_request_matches(source: dict[str, object], request: dict[str, object]) -> None:
    if request["artifact_id"] != source["source_artifact_id"] or request["action_type"] != "apply_patch":
        raise ValidationError("ReviewRequest does not authorize this patch artifact.", code="review_request_invalid")
    payload = request.get("payload")
    if not isinstance(payload, dict):
        raise ValidationError("ReviewRequest payload is invalid.", code="review_request_invalid")
    if payload.get("target_artifact_id") != source["target_artifact_id"]:
        raise ValidationError("ReviewRequest target does not match this apply request.", code="review_request_invalid")
    if payload.get("base_version_id") != source["base_version_id"]:
        raise ValidationError("ReviewRequest base version does not match this apply request.", code="review_request_invalid")


def _review_payload(source: dict[str, object]) -> dict[str, object]:
    return {
        "action_type": "apply_patch",
        "patch_artifact_id": source["patch_artifact_id"],
        "diff_artifact_id": source["diff_artifact_id"],
        "target_artifact_id": source["target_artifact_id"],
        "base_version_id": source["base_version_id"],
        "expected_base_checksum": source["expected_base_checksum"],
    }


def _apply_approved_patch(source: dict[str, object], *, test_run_id: str) -> dict[str, object]:
    existing_applied = _existing_application(source, statuses={"applied"}, test_run_id=test_run_id)
    if existing_applied is not None:
        existing_applied["idempotent"] = True
        return existing_applied

    try:
        current = get_current_artifact_version_record(str(source["target_artifact_id"]), test_run_id=test_run_id)
        failure_code = _precondition_failure_code(source, current)
        if failure_code is not None:
            existing_failure = _existing_application(
                source,
                statuses={"failed"},
                test_run_id=test_run_id,
            )
            if existing_failure is not None and existing_failure.get("error_code") == failure_code:
                existing_failure["idempotent"] = True
                return existing_failure
            return _record_application(
                source,
                status="failed",
                error_code=failure_code,
                result_version_id=None,
                test_run_id=test_run_id,
            )
        current_text = _read_current_text(current)
        result_text = apply_unified_text_patch(current_text, str(source["patch_text"]))
        return append_artifact_version_with_patch_application(
            str(source["target_artifact_id"]),
            content=result_text,
            parent_version_id=str(source["base_version_id"]),
            patch_artifact_id=source["patch_artifact_id"] if isinstance(source["patch_artifact_id"], str) else None,
            diff_artifact_id=source["diff_artifact_id"] if isinstance(source["diff_artifact_id"], str) else None,
            target_artifact_id=str(source["target_artifact_id"]),
            base_version_id=str(source["base_version_id"]),
            test_run_id=test_run_id,
        )
    except PatchConflictError:
        existing_conflict = _existing_application(source, statuses={"conflict"}, test_run_id=test_run_id)
        if existing_conflict is not None:
            existing_conflict["idempotent"] = True
            return existing_conflict
        return _record_application(
            source,
            status="conflict",
            error_code="artifact_apply_conflict",
            result_version_id=None,
            test_run_id=test_run_id,
        )
    except ValidationError as exc:
        return _record_application(
            source,
            status="failed",
            error_code=exc.code or "artifact_apply_failed",
            result_version_id=None,
            test_run_id=test_run_id,
        )
    except NotFoundError as exc:
        raise ValidationError("Patch apply target was not found.", code="artifact_apply_target_not_found") from exc


def _precondition_failure_code(source: dict[str, object], current: dict[str, object]) -> str | None:
    if current["version_id"] != source["base_version_id"]:
        return "artifact_apply_stale_base"
    expected_checksum = source.get("expected_base_checksum")
    if expected_checksum is not None and current["checksum"] != expected_checksum:
        return "artifact_apply_checksum_mismatch"
    return None


def _read_current_text(current: dict[str, object]) -> str:
    mime_type = str(current["artifact_mime_type"])
    if not _is_text_mime_type(mime_type):
        raise ValidationError("Patch apply supports text artifacts only.", code="artifact_apply_unsupported_content")
    raw = read_content(str(current["storage_key"]), expected_checksum=str(current["checksum"]))
    if b"\x00" in raw:
        raise ValidationError("Patch target appears to be binary content.", code="artifact_apply_unsupported_content")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("Patch target must be valid UTF-8.", code="artifact_apply_unsupported_content") from exc


def _record_application(
    source: dict[str, object],
    *,
    status: str,
    error_code: str | None,
    result_version_id: str | None,
    test_run_id: str,
) -> dict[str, object]:
    return create_patch_application(
        patch_artifact_id=source["patch_artifact_id"] if isinstance(source["patch_artifact_id"], str) else None,
        diff_artifact_id=source["diff_artifact_id"] if isinstance(source["diff_artifact_id"], str) else None,
        target_artifact_id=str(source["target_artifact_id"]),
        base_version_id=str(source["base_version_id"]),
        result_version_id=result_version_id,
        status=status,
        error_code=error_code,
        test_run_id=test_run_id,
    )


def _existing_application(
    source: dict[str, object],
    *,
    statuses: set[str],
    test_run_id: str,
) -> dict[str, object] | None:
    return latest_patch_application_for_source(
        patch_artifact_id=source["patch_artifact_id"] if isinstance(source["patch_artifact_id"], str) else None,
        diff_artifact_id=source["diff_artifact_id"] if isinstance(source["diff_artifact_id"], str) else None,
        target_artifact_id=str(source["target_artifact_id"]),
        base_version_id=str(source["base_version_id"]),
        statuses=statuses,
        test_run_id=test_run_id,
    )


def apply_unified_text_patch(source_text: str, patch_text: str) -> str:
    hunks = _parse_unified_patch(patch_text)
    if not hunks:
        raise ValidationError("Patch content has no unified diff hunks.", code="artifact_apply_invalid_patch")

    lines = source_text.splitlines()
    had_trailing_newline = source_text.endswith("\n")
    offset = 0
    cursor = 0
    for hunk in hunks:
        pattern = [content for op, content in hunk["lines"] if op in {" ", "-"}]
        replacement = [content for op, content in hunk["lines"] if op in {" ", "+"}]
        old_start = hunk["old_start"]
        index = _find_hunk_index(lines, pattern, old_start=old_start, offset=offset, cursor=cursor)
        if index is None:
            raise PatchConflictError()
        lines[index : index + len(pattern)] = replacement
        cursor = index + len(replacement)
        offset += len(replacement) - len(pattern)

    if not lines:
        return "\n" if had_trailing_newline else ""
    return "\n".join(lines) + ("\n" if had_trailing_newline else "")


def _parse_unified_patch(patch_text: str) -> list[dict[str, object]]:
    hunks: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in patch_text.splitlines():
        if line.startswith("@@"):
            match = _HUNK_RANGE_RE.search(line)
            current = {
                "old_start": int(match.group(1)) if match is not None else None,
                "lines": [],
            }
            hunks.append(current)
            continue
        if current is None:
            continue
        if line.startswith("\\ No newline"):
            continue
        if line[:1] in {" ", "-", "+"}:
            lines = current["lines"]
            if isinstance(lines, list):
                lines.append((line[0], line[1:]))
    return [hunk for hunk in hunks if hunk["lines"]]


def _find_hunk_index(
    lines: list[str],
    pattern: list[str],
    *,
    old_start: object,
    offset: int,
    cursor: int,
) -> int | None:
    if not pattern:
        if isinstance(old_start, int):
            return max(0, min(len(lines), old_start - 1 + offset))
        return cursor

    if isinstance(old_start, int):
        hinted = old_start - 1 + offset
        for index in _candidate_indexes(lines, pattern, start=max(0, hinted - 3), end=min(len(lines), hinted + 4)):
            return index

    for index in _candidate_indexes(lines, pattern, start=cursor, end=len(lines)):
        return index
    for index in _candidate_indexes(lines, pattern, start=0, end=cursor):
        return index
    return None


def _candidate_indexes(lines: list[str], pattern: list[str], *, start: int, end: int):
    max_index = len(lines) - len(pattern)
    for index in range(start, min(end, max_index) + 1):
        if lines[index : index + len(pattern)] == pattern:
            yield index


def _is_text_mime_type(mime_type: str) -> bool:
    return mime_type.startswith(_TEXT_MIME_PREFIXES) or mime_type in _TEXT_MIME_TYPES


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string when provided.", code="artifact_apply_invalid")
    return value.strip()
