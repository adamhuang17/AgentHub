from __future__ import annotations

import uuid
import re
from sqlite3 import Connection, Row

from services.api.app.artifacts.repository import _ensure_artifact_tables
from services.api.app.execution.events import record_event
from services.api.app.memory.schema import PIN_SOURCE_TYPES
from services.api.app.shared.database import connect
from services.api.app.shared.errors import NotFoundError, ValidationError
from services.api.app.shared.time import utc_now


_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk_[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{8,}"),
    re.compile(r"(?i)\b(api[_ -]?key|token|secret|password|credential)\s*[:=]\s*([^\s,;]+)"),
)


def ensure_pinned_context_table(connection: Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS pinned_context (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            source_type TEXT NOT NULL CHECK (
                source_type IN ('message', 'artifact', 'artifact_version', 'text_note')
            ),
            source_id TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pinned_context_conversation_created
            ON pinned_context(conversation_id, created_at ASC)
        """
    )


def create_pin(
    *,
    conversation_id: str,
    source_type: str,
    source_id: str | None,
    note: str | None,
    test_run_id: str,
) -> dict[str, object]:
    clean_source_type = source_type.strip()
    if clean_source_type not in PIN_SOURCE_TYPES:
        raise ValidationError("Unsupported pin source_type.", code="pin_source_type_invalid")
    clean_source_id = _clean_optional(source_id)
    clean_note = _redact_note(_clean_optional(note))

    if clean_source_type == "text_note":
        if not clean_note:
            raise ValidationError("text_note pins require note.", code="pin_note_required")
    elif not clean_source_id:
        raise ValidationError(f"{clean_source_type} pins require source_id.", code="pin_source_required")

    pin_id = f"pin_{uuid.uuid4().hex}"
    created_at = utc_now()
    with connect() as connection:
        ensure_pinned_context_table(connection)
        _require_conversation(connection, conversation_id, test_run_id=test_run_id)
        _validate_source(
            connection,
            conversation_id=conversation_id,
            source_type=clean_source_type,
            source_id=clean_source_id,
            test_run_id=test_run_id,
        )
        connection.execute(
            """
            INSERT INTO pinned_context (
                id, conversation_id, source_type, source_id, note, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (pin_id, conversation_id, clean_source_type, clean_source_id, clean_note, created_at),
        )
        record_event(
            connection,
            conversation_id=conversation_id,
            event_type="pin.created",
            payload={
                "pin_id": pin_id,
                "source_type": clean_source_type,
                "source_id": clean_source_id,
                "has_note": clean_note is not None,
            },
            created_at=created_at,
        )
    return get_pin(pin_id, test_run_id=test_run_id)


def get_pin(pin_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        ensure_pinned_context_table(connection)
        row = connection.execute(
            """
            SELECT pc.*
            FROM pinned_context pc
            JOIN conversations c ON c.id = pc.conversation_id
            WHERE pc.id = ? AND c.test_run_id = ?
            """,
            (pin_id, test_run_id),
        ).fetchone()
    if row is None:
        raise NotFoundError("Pin not found.")
    return _pin_from_row(row)


def list_pins(conversation_id: str, *, test_run_id: str) -> list[dict[str, object]]:
    with connect() as connection:
        ensure_pinned_context_table(connection)
        _require_conversation(connection, conversation_id, test_run_id=test_run_id)
        rows = connection.execute(
            """
            SELECT *
            FROM pinned_context
            WHERE conversation_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_id,),
        ).fetchall()
    return [_pin_from_row(row) for row in rows]


def _validate_source(
    connection: Connection,
    *,
    conversation_id: str,
    source_type: str,
    source_id: str | None,
    test_run_id: str,
) -> None:
    if source_type == "text_note":
        return
    if source_id is None:
        raise ValidationError("source_id is required.", code="pin_source_required")
    if source_type == "message":
        row = connection.execute(
            """
            SELECT id
            FROM messages
            WHERE id = ? AND conversation_id = ? AND test_run_id = ?
            """,
            (source_id, conversation_id, test_run_id),
        ).fetchone()
        if row is None:
            raise ValidationError(
                "source_id must reference a message in the same conversation.",
                code="pin_source_invalid",
            )
        return
    if source_type == "artifact":
        _ensure_artifact_tables(connection)
        row = connection.execute(
            """
            SELECT id
            FROM artifacts
            WHERE id = ? AND conversation_id = ? AND test_run_id = ?
            """,
            (source_id, conversation_id, test_run_id),
        ).fetchone()
        if row is None:
            raise ValidationError(
                "source_id must reference an artifact in the same conversation.",
                code="pin_source_invalid",
            )
        return
    if source_type == "artifact_version":
        _ensure_artifact_tables(connection)
        row = connection.execute(
            """
            SELECT av.id
            FROM artifact_versions av
            JOIN artifacts a ON a.id = av.artifact_id
            WHERE av.id = ?
                AND av.test_run_id = ?
                AND a.test_run_id = ?
                AND a.conversation_id = ?
            """,
            (source_id, test_run_id, test_run_id, conversation_id),
        ).fetchone()
        if row is None:
            raise ValidationError(
                "source_id must reference an artifact version in the same conversation.",
                code="pin_source_invalid",
            )


def _require_conversation(connection: Connection, conversation_id: str, *, test_run_id: str) -> None:
    row = connection.execute(
        "SELECT id FROM conversations WHERE id = ? AND test_run_id = ?",
        (conversation_id, test_run_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("Conversation not found.")


def _pin_from_row(row: Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    return clean or None


def _redact_note(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value
    for pattern in _SECRET_PATTERNS:
        clean = pattern.sub("[redacted]", clean)
    return clean
