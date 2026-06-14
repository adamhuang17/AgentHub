from __future__ import annotations

import difflib
import json
import re
import uuid
from typing import Any

from services.api.app.artifacts.repository import (
    create_artifact,
    create_artifact_diff_record,
    get_artifact_version_record,
    get_diff_artifact,
)
from services.api.app.artifacts.schema import validate_diff_request
from services.api.app.artifacts.store import read_content
from services.api.app.shared.errors import NotFoundError, ValidationError


_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_lines>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_lines>\d+))? @@(?: (?P<section>.*))?$"
)
_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_MIME_TYPES = {
    "application/json",
    "application/javascript",
    "application/xml",
    "application/x-python-code",
    "application/vnd.agenthub.source+json",
    "application/vnd.agenthub.diff+json",
}


def create_diff_artifact_from_request(raw: dict[str, Any], *, test_run_id: str) -> dict[str, object]:
    request = validate_diff_request(raw)
    base = _version_record(
        str(request["base_artifact_id"]),
        str(request["base_version_id"]),
        test_run_id=test_run_id,
        role="base",
    )
    target = _version_record(
        str(request["target_artifact_id"]),
        str(request["target_version_id"]),
        test_run_id=test_run_id,
        role="target",
    )
    if base["conversation_id"] != target["conversation_id"]:
        raise ValidationError(
            "Base and target artifacts must belong to the same conversation.",
            code="artifact_diff_source_invalid",
        )

    _validate_expected_checksum(request.get("base_checksum"), base, role="base")
    _validate_expected_checksum(request.get("target_checksum"), target, role="target")

    base_text = _read_text_artifact(base, role="base")
    target_text = _read_text_artifact(target, role="target")
    path = str(request.get("path") or target["artifact_title"] or base["artifact_title"])
    diff_artifact_id = f"art_{uuid.uuid4().hex}"
    diff = build_text_diff(
        base_text=base_text,
        target_text=target_text,
        path=path,
        diff_artifact_id=diff_artifact_id,
        base_artifact_id=str(base["artifact_id"]),
        base_version_id=str(base["version_id"]),
        target_artifact_id=str(target["artifact_id"]),
        target_version_id=str(target["version_id"]),
    )
    title = str(request.get("title") or f"Diff Preview: {path}")
    content = json.dumps(diff, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    artifact = create_artifact(
        conversation_id=str(base["conversation_id"]),
        artifact_type=str(request["type"]),
        title=title,
        mime_type="application/vnd.agenthub.diff+json",
        content=content,
        test_run_id=test_run_id,
        artifact_id=diff_artifact_id,
    )
    create_artifact_diff_record(
        diff_artifact_id=diff_artifact_id,
        base_artifact_id=str(base["artifact_id"]),
        base_version_id=str(base["version_id"]),
        target_artifact_id=str(target["artifact_id"]),
        target_version_id=str(target["version_id"]),
        files=diff["files"],
        hunks=diff["hunks"],
        additions=int(diff["additions"]),
        deletions=int(diff["deletions"]),
        checksum=str(artifact["checksum"]),
        base_checksum=str(base["checksum"]),
        target_checksum=str(target["checksum"]),
        test_run_id=test_run_id,
    )
    return get_diff_artifact(diff_artifact_id, test_run_id=test_run_id)


def build_text_diff(
    *,
    base_text: str,
    target_text: str,
    path: str,
    diff_artifact_id: str,
    base_artifact_id: str,
    base_version_id: str,
    target_artifact_id: str,
    target_version_id: str,
) -> dict[str, object]:
    base_lines = base_text.splitlines()
    target_lines = target_text.splitlines()
    unified_lines = list(
        difflib.unified_diff(
            base_lines,
            target_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    unified_diff = "\n".join(unified_lines)
    if unified_diff:
        unified_diff += "\n"

    additions = sum(1 for line in unified_lines if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in unified_lines if line.startswith("-") and not line.startswith("---"))
    hunks = _parse_hunks(unified_lines, path=path)
    file_entry = {
        "path": path,
        "old_path": path,
        "new_path": path,
        "status": "modified" if additions or deletions else "unchanged",
        "additions": additions,
        "deletions": deletions,
        "hunks": hunks,
        "unified_diff": unified_diff,
    }
    flattened_hunks = [{**hunk, "file_path": path} for hunk in hunks]
    return {
        "diff_artifact_id": diff_artifact_id,
        "base_artifact_id": base_artifact_id,
        "base_version_id": base_version_id,
        "target_artifact_id": target_artifact_id,
        "target_version_id": target_version_id,
        "files": [file_entry],
        "hunks": flattened_hunks,
        "additions": additions,
        "deletions": deletions,
    }


def _version_record(artifact_id: str, version_id: str, *, test_run_id: str, role: str) -> dict[str, object]:
    try:
        return get_artifact_version_record(artifact_id, version_id, test_run_id=test_run_id)
    except NotFoundError as exc:
        raise ValidationError(
            f"{role} artifact version was not found.",
            code=f"artifact_diff_{role}_not_found",
        ) from exc


def _read_text_artifact(version: dict[str, object], *, role: str) -> str:
    mime_type = str(version["artifact_mime_type"])
    if not _is_text_mime_type(mime_type):
        raise ValidationError(
            f"{role} artifact content type is not supported for text diff preview.",
            code="artifact_diff_unsupported_content",
        )
    try:
        raw = read_content(str(version["storage_key"]), expected_checksum=str(version["checksum"]))
    except ValidationError as exc:
        if exc.code == "artifact_checksum_mismatch":
            raise ValidationError(
                f"{role} artifact checksum verification failed.",
                code="artifact_diff_checksum_mismatch",
            ) from exc
        raise
    if b"\x00" in raw:
        raise ValidationError(
            f"{role} artifact appears to be binary content.",
            code="artifact_diff_unsupported_content",
        )
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            f"{role} artifact must be valid UTF-8 text for diff preview.",
            code="artifact_diff_unsupported_content",
        ) from exc


def _validate_expected_checksum(expected: object, version: dict[str, object], *, role: str) -> None:
    if expected is None:
        return
    if str(expected) != str(version["checksum"]):
        raise ValidationError(
            f"{role} artifact checksum precondition does not match the stored version.",
            code="artifact_diff_checksum_mismatch",
        )


def _parse_hunks(unified_lines: list[str], *, path: str) -> list[dict[str, object]]:
    hunks: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    old_line = 0
    new_line = 0

    for line in unified_lines:
        match = _HUNK_HEADER_RE.match(line)
        if match is not None:
            if current is not None:
                hunks.append(current)
            old_start = int(match.group("old_start"))
            new_start = int(match.group("new_start"))
            old_lines = int(match.group("old_lines") or "1")
            new_lines = int(match.group("new_lines") or "1")
            old_line = old_start
            new_line = new_start
            current = {
                "path": path,
                "header": line,
                "old_start": old_start,
                "old_lines": old_lines,
                "new_start": new_start,
                "new_lines": new_lines,
                "section": match.group("section") or "",
                "lines": [],
            }
            continue

        if current is None or not line:
            continue

        prefix = line[0]
        content = line[1:]
        lines = current["lines"]
        if not isinstance(lines, list):
            continue
        if prefix == " ":
            lines.append(
                {
                    "type": "context",
                    "content": content,
                    "old_line": old_line,
                    "new_line": new_line,
                }
            )
            old_line += 1
            new_line += 1
        elif prefix == "+":
            lines.append(
                {
                    "type": "addition",
                    "content": content,
                    "old_line": None,
                    "new_line": new_line,
                }
            )
            new_line += 1
        elif prefix == "-":
            lines.append(
                {
                    "type": "deletion",
                    "content": content,
                    "old_line": old_line,
                    "new_line": None,
                }
            )
            old_line += 1

    if current is not None:
        hunks.append(current)
    return hunks


def _is_text_mime_type(mime_type: str) -> bool:
    return mime_type.startswith(_TEXT_MIME_PREFIXES) or mime_type in _TEXT_MIME_TYPES
