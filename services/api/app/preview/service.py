from __future__ import annotations

import json

from services.api.app.artifacts.repository import (
    get_artifact,
    get_artifact_version_record,
    get_current_artifact_version_record,
    list_artifact_versions,
)
from services.api.app.artifacts.office import OFFICE_ARTIFACT_TYPES, OFFICE_MIME_TYPES, extract_office_text
from services.api.app.artifacts.schema import DIFF_ARTIFACT_TYPES
from services.api.app.artifacts.store import read_content
from services.api.app.shared.errors import NotFoundError, ValidationError


TEXT_PREVIEW_ARTIFACT_TYPES = {
    "document",
    "source_file",
    "code_file",
    "markdown_doc",
    "web_preview",
}
_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_MIME_TYPES = {
    "application/json",
    "application/javascript",
    "application/xml",
    "application/x-python-code",
    "application/vnd.agenthub.source+json",
}


def preview_artifact(
    artifact_id: str,
    *,
    test_run_id: str,
    version: int | None = None,
    version_id: str | None = None,
) -> dict[str, object]:
    artifact = get_artifact(artifact_id, test_run_id=test_run_id)
    artifact_type = str(artifact["type"])
    selected_version = _select_version(
        artifact,
        test_run_id=test_run_id,
        version=version,
        version_id=version_id,
    )

    if artifact_type in TEXT_PREVIEW_ARTIFACT_TYPES:
        return _text_preview(artifact, selected_version)
    if artifact_type in OFFICE_ARTIFACT_TYPES or str(artifact["mime_type"]) in OFFICE_MIME_TYPES:
        return _office_preview(artifact, selected_version)
    if artifact_type in DIFF_ARTIFACT_TYPES:
        return _structured_diff_preview(artifact, selected_version)
    raise ValidationError(
        "Artifact type is not supported for read-only preview.",
        code="artifact_preview_unsupported",
    )


def _text_preview(artifact: dict[str, object], version: dict[str, object]) -> dict[str, object]:
    mime_type = str(artifact["mime_type"])
    if not _is_text_mime_type(mime_type):
        raise ValidationError(
            "Artifact content type is not supported for read-only preview.",
            code="artifact_preview_unsupported",
        )
    raw = _read_verified_content(version)
    if b"\x00" in raw:
        raise ValidationError(
            "Artifact appears to be binary content and cannot be previewed.",
            code="artifact_preview_unsupported",
        )
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            "Artifact preview supports valid UTF-8 text only.",
            code="artifact_preview_unsupported",
        ) from exc

    return {
        **_preview_base(artifact, version),
        "preview_type": "text",
        "encoding": "utf-8",
        "content": content,
    }


def _structured_diff_preview(artifact: dict[str, object], version: dict[str, object]) -> dict[str, object]:
    raw = _read_verified_content(version)
    try:
        diff_payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "Diff artifact preview content is not valid structured JSON.",
            code="artifact_preview_unsupported",
        ) from exc
    if not isinstance(diff_payload, dict):
        raise ValidationError(
            "Diff artifact preview content must be an object.",
            code="artifact_preview_unsupported",
        )
    files = diff_payload.get("files")
    hunks = diff_payload.get("hunks")
    if not isinstance(files, list) or not isinstance(hunks, list):
        raise ValidationError(
            "Diff artifact preview content must include files and hunks.",
            code="artifact_preview_unsupported",
        )

    return {
        **_preview_base(artifact, version),
        "preview_type": "structured_diff",
        "diff_artifact_id": artifact["id"],
        "base_artifact_id": diff_payload.get("base_artifact_id"),
        "base_version_id": diff_payload.get("base_version_id"),
        "target_artifact_id": diff_payload.get("target_artifact_id"),
        "target_version_id": diff_payload.get("target_version_id"),
        "files": files,
        "hunks": hunks,
        "additions": int(diff_payload.get("additions") or 0),
        "deletions": int(diff_payload.get("deletions") or 0),
    }


def _office_preview(artifact: dict[str, object], version: dict[str, object]) -> dict[str, object]:
    raw = _read_verified_content(version)
    content = extract_office_text(
        raw,
        artifact_type=str(artifact["type"]),
        mime_type=str(artifact["mime_type"]),
    )
    if not content:
        raise ValidationError(
            "Office artifact preview text could not be extracted.",
            code="artifact_preview_unsupported",
        )
    return {
        **_preview_base(artifact, version),
        "preview_type": "office_document",
        "encoding": "utf-8",
        "content": content,
    }


def _preview_base(artifact: dict[str, object], version: dict[str, object]) -> dict[str, object]:
    return {
        "artifact_id": artifact["id"],
        "current_version_id": artifact["current_version_id"],
        "version_id": version["version_id"],
        "version": version["version"],
        "checksum": version["checksum"],
        "created_by_run_id": artifact.get("created_by_run_id"),
        "type": artifact["type"],
        "mime_type": artifact["mime_type"],
        "status": artifact["status"],
        "read_only": True,
        "source": "artifact_store",
    }


def _select_version(
    artifact: dict[str, object],
    *,
    test_run_id: str,
    version: int | None,
    version_id: str | None,
) -> dict[str, object]:
    artifact_id = str(artifact["id"])
    if version_id is not None:
        selected = _normalize_version_record(
            get_artifact_version_record(artifact_id, version_id, test_run_id=test_run_id)
        )
        if version is not None and int(selected["version"]) != version:
            raise ValidationError(
                "version and version_id refer to different ArtifactVersion records.",
                code="artifact_preview_invalid_version",
            )
        return selected
    if version is None:
        return _normalize_version_record(get_current_artifact_version_record(artifact_id, test_run_id=test_run_id))

    for item in list_artifact_versions(artifact_id, test_run_id=test_run_id):
        if int(item["version"]) == version:
            return {
                "version_id": item["id"],
                "version": item["version"],
                "storage_key": item["storage_key"],
                "checksum": item["checksum"],
                "parent_version_id": item["parent_version_id"],
            }
    raise NotFoundError("ArtifactVersion not found.")


def _normalize_version_record(record: dict[str, object]) -> dict[str, object]:
    return {
        "version_id": record["version_id"],
        "version": record["version"],
        "storage_key": record["storage_key"],
        "checksum": record["checksum"],
        "parent_version_id": record["parent_version_id"],
    }


def _read_verified_content(version: dict[str, object]) -> bytes:
    try:
        return read_content(
            str(version["storage_key"]),
            expected_checksum=str(version["checksum"]),
        )
    except ValidationError as exc:
        if exc.code == "artifact_checksum_mismatch":
            raise ValidationError(
                "Artifact preview checksum verification failed.",
                code="artifact_preview_checksum_mismatch",
            ) from exc
        raise


def _is_text_mime_type(mime_type: str) -> bool:
    return mime_type.startswith(_TEXT_MIME_PREFIXES) or mime_type in _TEXT_MIME_TYPES
