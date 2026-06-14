from __future__ import annotations

import json
import re
from sqlite3 import Connection, Row

from services.api.app.artifacts.repository import list_artifacts
from services.api.app.execution.events import append_event
from services.api.app.memory.pinned_context import ensure_pinned_context_table, list_pins
from services.api.app.memory.schema import context_constraints, context_ref, context_summary
from services.api.app.shared.database import connect
from services.api.app.shared.errors import NotFoundError, ValidationError


_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk_[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{8,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(
        r"(?i)\b(api[_ -]?key|token|secret|password|credential)\s*[:=]\s*([^\s,;]+)"
    ),
    re.compile(
        r"(?im)^[A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z0-9_]*\s*=.+$"
    ),
)


class ContextBuildError(ValidationError):
    def __init__(self, message: str, *, code: str = "context_build_failed") -> None:
        super().__init__(message, code=code)


def build_context_bundle(
    conversation_id: str,
    *,
    test_run_id: str,
    emit_event: bool = True,
) -> dict[str, object]:
    try:
        bundle = _build_context_bundle(conversation_id, test_run_id=test_run_id)
    except NotFoundError:
        raise
    except Exception as exc:
        code = getattr(exc, "code", "context_build_failed")
        if emit_event:
            _record_build_failed(conversation_id, code=code, message=str(exc))
        if isinstance(exc, ValidationError):
            raise ContextBuildError(str(exc), code=code) from exc
        raise ContextBuildError("Context build failed.", code=code) from exc

    if emit_event:
        append_event(
            conversation_id=conversation_id,
            event_type="context.built",
            payload={
                "conversation_id": conversation_id,
                "context_summary": bundle["context_summary"],
            },
        )
    return bundle


def build_context_bundle_for_message(
    message_id: str,
    *,
    test_run_id: str,
    emit_event: bool = True,
) -> dict[str, object]:
    conversation_id = _conversation_id_for_message(message_id, test_run_id=test_run_id)
    return build_context_bundle(conversation_id, test_run_id=test_run_id, emit_event=emit_event)


def build_context_bundle_for_plan_step(
    plan_step_id: str,
    *,
    test_run_id: str,
    emit_event: bool = True,
) -> dict[str, object]:
    conversation_id = _conversation_id_for_plan_step(plan_step_id, test_run_id=test_run_id)
    return build_context_bundle(conversation_id, test_run_id=test_run_id, emit_event=emit_event)


def summarize_context_bundle(bundle: dict[str, object]) -> dict[str, object]:
    return context_summary(bundle)


def ref_for_context_bundle(bundle: dict[str, object]) -> dict[str, object]:
    return context_ref(bundle)


def _build_context_bundle(conversation_id: str, *, test_run_id: str) -> dict[str, object]:
    constraints = context_constraints()
    with connect() as connection:
        ensure_pinned_context_table(connection)
        _require_conversation(connection, conversation_id, test_run_id=test_run_id)
        recent_messages = _recent_messages(
            connection,
            conversation_id,
            test_run_id=test_run_id,
            max_recent_messages=constraints.max_recent_messages,
        )

    budget = _TextBudget(max_total=constraints.max_total_chars)
    recent_payload = [
        _message_context(message, budget=budget, max_chars=constraints.max_message_chars)
        for message in recent_messages
    ]
    pinned_payload = [
        _pin_context(pin, budget=budget, max_chars=constraints.max_message_chars, test_run_id=test_run_id)
        for pin in list_pins(conversation_id, test_run_id=test_run_id)
    ]
    artifact_refs = [
        _artifact_ref(artifact)
        for artifact in list_artifacts(test_run_id=test_run_id, conversation_id=conversation_id)
    ]

    bundle: dict[str, object] = {
        "conversation_id": conversation_id,
        "recent_messages": recent_payload,
        "pinned_context": pinned_payload,
        "artifact_refs": artifact_refs,
        "conversation_summary": None,
        "selected_ranges": [],
        "constraints": constraints.to_response(),
        "context_summary": {},
    }
    summary = context_summary(bundle)
    summary["truncated"] = bool(summary["truncated"] or budget.truncated)
    bundle["context_summary"] = summary
    return bundle


def _recent_messages(
    connection: Connection,
    conversation_id: str,
    *,
    test_run_id: str,
    max_recent_messages: int,
) -> list[dict[str, object]]:
    if max_recent_messages <= 0:
        return []
    rows = connection.execute(
        """
        SELECT *
        FROM messages
        WHERE conversation_id = ? AND test_run_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (conversation_id, test_run_id, max_recent_messages),
    ).fetchall()
    return [_message_from_row(row) for row in reversed(rows)]


def _message_context(
    message: dict[str, object],
    *,
    budget: "_TextBudget",
    max_chars: int,
) -> dict[str, object]:
    text, truncated = _bounded_text(_message_text(message), budget=budget, max_chars=max_chars)
    return {
        "id": message["id"],
        "sender_type": message["sender_type"],
        "sender_id": message["sender_id"],
        "message_type": message["message_type"],
        "text": text,
        "created_at": message["created_at"],
        "truncated": truncated,
    }


def _pin_context(
    pin: dict[str, object],
    *,
    budget: "_TextBudget",
    max_chars: int,
    test_run_id: str,
) -> dict[str, object]:
    source_type = str(pin["source_type"])
    resolved: dict[str, object] | None
    if source_type == "message":
        resolved = _resolve_message_pin(str(pin["source_id"]), budget=budget, max_chars=max_chars, test_run_id=test_run_id)
    elif source_type == "artifact":
        resolved = _resolve_artifact_pin(str(pin["source_id"]), test_run_id=test_run_id)
    elif source_type == "artifact_version":
        resolved = _resolve_artifact_version_pin(str(pin["source_id"]), test_run_id=test_run_id)
    else:
        note, truncated = _bounded_text(str(pin.get("note") or ""), budget=budget, max_chars=max_chars)
        resolved = {"source_type": "text_note", "text": note, "truncated": truncated}

    return {
        "id": pin["id"],
        "source_type": source_type,
        "source_id": pin["source_id"],
        "note": _redact_sensitive_text(str(pin["note"])) if isinstance(pin.get("note"), str) else None,
        "resolved": resolved,
        "created_at": pin["created_at"],
    }


def _resolve_message_pin(
    message_id: str,
    *,
    budget: "_TextBudget",
    max_chars: int,
    test_run_id: str,
) -> dict[str, object]:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM messages WHERE id = ? AND test_run_id = ?",
            (message_id, test_run_id),
        ).fetchone()
    if row is None:
        raise ValidationError("Pinned message no longer exists.", code="context_pin_source_missing")
    message = _message_from_row(row)
    text, truncated = _bounded_text(_message_text(message), budget=budget, max_chars=max_chars)
    return {
        "id": message["id"],
        "conversation_id": message["conversation_id"],
        "sender_type": message["sender_type"],
        "sender_id": message["sender_id"],
        "message_type": message["message_type"],
        "text": text,
        "created_at": message["created_at"],
        "truncated": truncated,
    }


def _resolve_artifact_pin(artifact_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT
                a.id AS artifact_id,
                a.current_version_id,
                a.type,
                a.title,
                a.status,
                a.mime_type,
                av.checksum
            FROM artifacts a
            LEFT JOIN artifact_versions av ON av.id = a.current_version_id
            WHERE a.id = ? AND a.test_run_id = ?
            """,
            (artifact_id, test_run_id),
        ).fetchone()
    if row is None:
        raise ValidationError("Pinned artifact no longer exists.", code="context_pin_source_missing")
    return {
        "artifact_id": row["artifact_id"],
        "current_version_id": row["current_version_id"],
        "type": row["type"],
        "title": row["title"],
        "status": row["status"],
        "checksum": row["checksum"],
        "mime_type": row["mime_type"],
    }


def _resolve_artifact_version_pin(version_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT
                a.id AS artifact_id,
                av.id AS version_id,
                av.version,
                av.checksum,
                av.parent_version_id
            FROM artifact_versions av
            JOIN artifacts a ON a.id = av.artifact_id
            WHERE av.id = ? AND av.test_run_id = ? AND a.test_run_id = ?
            """,
            (version_id, test_run_id, test_run_id),
        ).fetchone()
    if row is None:
        raise ValidationError("Pinned artifact version no longer exists.", code="context_pin_source_missing")
    return {
        "artifact_id": row["artifact_id"],
        "version_id": row["version_id"],
        "version": row["version"],
        "checksum": row["checksum"],
        "parent_version_id": row["parent_version_id"],
    }


def _artifact_ref(artifact: dict[str, object]) -> dict[str, object]:
    return {
        "artifact_id": artifact["id"],
        "current_version_id": artifact.get("current_version_id"),
        "type": artifact["type"],
        "title": artifact["title"],
        "status": artifact["status"],
        "checksum": artifact.get("checksum"),
        "mime_type": artifact["mime_type"],
    }


def _conversation_id_for_message(message_id: str, *, test_run_id: str) -> str:
    with connect() as connection:
        row = connection.execute(
            "SELECT conversation_id FROM messages WHERE id = ? AND test_run_id = ?",
            (message_id, test_run_id),
        ).fetchone()
    if row is None:
        raise NotFoundError("Message not found.")
    return str(row["conversation_id"])


def _conversation_id_for_plan_step(plan_step_id: str, *, test_run_id: str) -> str:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT t.conversation_id
            FROM plan_steps ps
            JOIN plans p ON p.id = ps.plan_id
            JOIN tasks t ON t.id = p.task_id
            WHERE ps.id = ? AND t.test_run_id = ?
            """,
            (plan_step_id, test_run_id),
        ).fetchone()
    if row is None:
        raise NotFoundError("Plan step not found.")
    return str(row["conversation_id"])


def _require_conversation(connection: Connection, conversation_id: str, *, test_run_id: str) -> None:
    row = connection.execute(
        "SELECT id FROM conversations WHERE id = ? AND test_run_id = ?",
        (conversation_id, test_run_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("Conversation not found.")


def _message_from_row(row: Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "sender_type": row["sender_type"],
        "sender_id": row["sender_id"],
        "message_type": row["message_type"],
        "content": json.loads(row["content_json"]),
        "created_at": row["created_at"],
    }


def _message_text(message: dict[str, object]) -> str:
    content = message.get("content")
    if isinstance(content, dict) and isinstance(content.get("final_content"), str):
        return content["final_content"]
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return content["text"]
    if isinstance(content, str):
        return content
    return ""


def _bounded_text(text: str, *, budget: "_TextBudget", max_chars: int) -> tuple[str, bool]:
    clean = _redact_sensitive_text(text)
    if not clean:
        return "", False
    truncated = len(clean) > max_chars
    clean = clean[:max_chars]
    remaining = budget.remaining()
    if remaining <= 0:
        budget.truncated = True
        return "", True
    if len(clean) > remaining:
        clean = clean[:remaining]
        truncated = True
    budget.consume(len(clean))
    if truncated:
        budget.truncated = True
    return clean, truncated


def _redact_sensitive_text(text: str) -> str:
    clean = text
    for pattern in _SECRET_PATTERNS:
        clean = pattern.sub(lambda match: _redaction(match), clean)
    return clean


def _redaction(match: re.Match[str]) -> str:
    if match.lastindex and match.lastindex >= 1:
        label = match.group(1)
        if label:
            return f"{label}=[redacted]"
    return "[redacted]"


def _record_build_failed(conversation_id: str, *, code: str, message: str) -> None:
    try:
        append_event(
            conversation_id=conversation_id,
            event_type="context.build_failed",
            payload={
                "conversation_id": conversation_id,
                "error_code": code,
                "message": message[:500],
            },
        )
    except Exception:
        pass


class _TextBudget:
    def __init__(self, *, max_total: int) -> None:
        self.max_total = max_total
        self.used = 0
        self.truncated = False

    def remaining(self) -> int:
        return max(0, self.max_total - self.used)

    def consume(self, count: int) -> None:
        self.used += max(0, count)
