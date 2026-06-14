from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from services.api.app.shared.database import database_path
from services.api.app.shared.errors import ValidationError
from services.api.app.shared.settings import get_settings


_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"sk_[A-Za-z0-9_-]{12,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]{12,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{12,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
_SECRET_ENV_MARKERS = ("key", "token", "secret", "password", "credential")


def artifact_store_root() -> Path:
    settings = get_settings()
    if settings.artifact_store_dir:
        return settings.artifact_store_dir
    return database_path().parent / "artifacts"


def storage_key_for(
    *,
    test_run_id: str,
    conversation_id: str,
    artifact_id: str,
    version: int,
) -> str:
    return "/".join(
        [
            _safe_segment(test_run_id),
            _safe_segment(conversation_id),
            _safe_segment(artifact_id),
            f"v{version}.bin",
        ]
    )


def write_content(storage_key: str, content: bytes | str) -> str:
    raw = _content_bytes(content)
    assert_no_secret_material(raw)

    path = _path_for_storage_key(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    checksum = checksum_bytes(raw)
    stored_checksum = checksum_bytes(path.read_bytes())
    if stored_checksum != checksum:
        raise ValidationError("Artifact checksum verification failed after write.", code="artifact_checksum_mismatch")
    return checksum


def read_content(storage_key: str, *, expected_checksum: str | None = None) -> bytes:
    path = _path_for_storage_key(storage_key)
    if not path.exists() or not path.is_file():
        raise ValidationError("Artifact content is missing from local store.", code="artifact_content_missing")
    raw = path.read_bytes()
    checksum = checksum_bytes(raw)
    if expected_checksum is not None and checksum != expected_checksum:
        raise ValidationError("Artifact checksum verification failed on read.", code="artifact_checksum_mismatch")
    return raw


def checksum_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def assert_no_secret_material(content: bytes | str) -> None:
    text = _content_bytes(content).decode("utf-8", errors="ignore")
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            raise ValidationError("Artifact content must not contain credential or secret material.", code="artifact_secret_forbidden")
    for name, value in os.environ.items():
        if not value or len(value) < 12:
            continue
        lowered = name.lower()
        if any(marker in lowered for marker in _SECRET_ENV_MARKERS) and value in text:
            raise ValidationError(
                "Artifact content must not contain credential or secret material.",
                code="artifact_secret_forbidden",
            )


def _content_bytes(content: bytes | str) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    raise ValidationError("Artifact content must be text or bytes.", code="artifact_invalid_content")


def _path_for_storage_key(storage_key: str) -> Path:
    if not storage_key or storage_key.startswith("/") or "\\" in storage_key:
        raise ValidationError("Invalid artifact storage key.", code="artifact_invalid_storage_key")
    root = artifact_store_root().resolve()
    path = (root / storage_key).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValidationError("Artifact storage key escapes the store root.", code="artifact_invalid_storage_key") from exc
    return path


def _safe_segment(value: str) -> str:
    clean = _SAFE_SEGMENT_RE.sub("_", value.strip()).strip("._")
    return clean or "default"
