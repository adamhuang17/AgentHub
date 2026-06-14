from __future__ import annotations

import json
import uuid
from sqlite3 import Connection, Row

from services.api.app.shared.database import connect
from services.api.app.shared.errors import NotFoundError, ValidationError
from services.api.app.shared.time import utc_now


EVENT_TYPES = {
    "message.created",
    "planner.decision_created",
    "planner.decision_failed",
    "router.output_invalid",
    "task.created",
    "plan.created",
    "step.created",
    "step.blocked",
    "step.started",
    "step.succeeded",
    "step.failed",
    "step.retry_requested",
    "task.status_updated",
    "agent_run.created",
    "agent_run.started",
    "agent_run.succeeded",
    "agent_run.failed",
    "artifact.created",
    "artifact.version_created",
    "diff.created",
    "review_request.created",
    "patch_application.applied",
    "patch_application.failed",
    "patch_application.conflict",
    "deployment_release.created",
    "deployment_release.published",
    "deployment_release.failed",
    "pin.created",
    "context.built",
    "context.build_failed",
}


def ensure_event_tables(connection: Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_event_cursors (
            conversation_id TEXT PRIMARY KEY,
            next_sequence INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_events (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            task_id TEXT,
            plan_id TEXT,
            step_id TEXT,
            run_id TEXT,
            artifact_id TEXT,
            deployment_id TEXT,
            sequence INTEGER NOT NULL,
            type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (conversation_id, sequence)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversation_events_conversation_sequence
            ON conversation_events(conversation_id, sequence ASC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversation_events_task_sequence
            ON conversation_events(task_id, sequence ASC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversation_events_run_sequence
            ON conversation_events(run_id, sequence ASC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversation_events_artifact_sequence
            ON conversation_events(artifact_id, sequence ASC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversation_events_deployment_sequence
            ON conversation_events(deployment_id, sequence ASC)
        """
    )


def record_event(
    connection: Connection,
    *,
    conversation_id: str,
    event_type: str,
    payload: dict[str, object],
    task_id: str | None = None,
    plan_id: str | None = None,
    step_id: str | None = None,
    run_id: str | None = None,
    artifact_id: str | None = None,
    deployment_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    validate_event_type(event_type)
    if not isinstance(payload, dict):
        raise ValidationError("event payload must be an object.", code="execution_event_invalid")

    ensure_event_tables(connection)
    sequence = _next_sequence(connection, conversation_id)
    event_id = f"cevt_{uuid.uuid4().hex}"
    created = created_at or utc_now()
    encoded_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    connection.execute(
        """
        INSERT INTO conversation_events (
            id, conversation_id, task_id, plan_id, step_id, run_id,
            artifact_id, deployment_id, sequence, type, payload_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            conversation_id,
            task_id,
            plan_id,
            step_id,
            run_id,
            artifact_id,
            deployment_id,
            sequence,
            event_type,
            encoded_payload,
            created,
        ),
    )
    return {
        "id": event_id,
        "conversation_id": conversation_id,
        "task_id": task_id,
        "plan_id": plan_id,
        "step_id": step_id,
        "run_id": run_id,
        "artifact_id": artifact_id,
        "deployment_id": deployment_id,
        "sequence": sequence,
        "type": event_type,
        "payload_json": payload,
        "payload": payload,
        "created_at": created,
    }


def append_event(
    *,
    conversation_id: str,
    event_type: str,
    payload: dict[str, object],
    task_id: str | None = None,
    plan_id: str | None = None,
    step_id: str | None = None,
    run_id: str | None = None,
    artifact_id: str | None = None,
    deployment_id: str | None = None,
) -> dict[str, object]:
    with connect() as connection:
        return record_event(
            connection,
            conversation_id=conversation_id,
            event_type=event_type,
            payload=payload,
            task_id=task_id,
            plan_id=plan_id,
            step_id=step_id,
            run_id=run_id,
            artifact_id=artifact_id,
            deployment_id=deployment_id,
        )


def list_events(
    conversation_id: str,
    *,
    test_run_id: str,
    after_sequence: int | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
    artifact_id: str | None = None,
    deployment_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    if after_sequence is not None and after_sequence < 0:
        raise ValidationError("after_sequence must be non-negative.", code="execution_event_invalid")
    if limit is not None and limit <= 0:
        raise ValidationError("limit must be positive.", code="execution_event_invalid")

    filters = ["conversation_id = ?"]
    params: list[object] = [conversation_id]
    if after_sequence is not None:
        filters.append("sequence > ?")
        params.append(after_sequence)
    if task_id is not None:
        filters.append("task_id = ?")
        params.append(task_id)
    if run_id is not None:
        filters.append("run_id = ?")
        params.append(run_id)
    if artifact_id is not None:
        filters.append("artifact_id = ?")
        params.append(artifact_id)
    if deployment_id is not None:
        filters.append("deployment_id = ?")
        params.append(deployment_id)

    query = f"""
        SELECT *
        FROM conversation_events
        WHERE {" AND ".join(filters)}
        ORDER BY sequence ASC
    """
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    with connect() as connection:
        ensure_event_tables(connection)
        _require_conversation(connection, conversation_id, test_run_id=test_run_id)
        rows = connection.execute(query, params).fetchall()
    return [_event_from_row(row) for row in rows]


def list_task_events(task_id: str, *, test_run_id: str) -> list[dict[str, object]]:
    with connect() as connection:
        ensure_event_tables(connection)
        task = connection.execute(
            """
            SELECT conversation_id, created_by_message_id
            FROM tasks
            WHERE id = ? AND test_run_id = ?
            """,
            (task_id, test_run_id),
        ).fetchone()
        if task is None:
            raise NotFoundError("Task not found.")
        rows = connection.execute(
            """
            SELECT *
            FROM conversation_events
            WHERE conversation_id = ?
            ORDER BY sequence ASC
            """,
            (task["conversation_id"],),
        ).fetchall()
    source_message_id = str(task["created_by_message_id"])
    events = [_event_from_row(row) for row in rows]
    return [
        event
        for event in events
        if event["task_id"] == task_id or _payload_message_id(event) == source_message_id
    ]


def validate_event_type(event_type: str) -> None:
    if event_type not in EVENT_TYPES:
        raise ValidationError(f"Unsupported conversation event type: {event_type}", code="execution_event_invalid")


def _next_sequence(connection: Connection, conversation_id: str) -> int:
    connection.execute(
        """
        INSERT INTO conversation_event_cursors (conversation_id, next_sequence)
        VALUES (?, 2)
        ON CONFLICT(conversation_id) DO UPDATE
            SET next_sequence = next_sequence + 1
        """,
        (conversation_id,),
    )
    row = connection.execute(
        """
        SELECT next_sequence - 1 AS sequence
        FROM conversation_event_cursors
        WHERE conversation_id = ?
        """,
        (conversation_id,),
    ).fetchone()
    return int(row["sequence"])


def _require_conversation(connection: Connection, conversation_id: str, *, test_run_id: str) -> None:
    row = connection.execute(
        "SELECT id FROM conversations WHERE id = ? AND test_run_id = ?",
        (conversation_id, test_run_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("Conversation not found.")


def _event_from_row(row: Row) -> dict[str, object]:
    payload = json.loads(row["payload_json"])
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "task_id": row["task_id"],
        "plan_id": row["plan_id"],
        "step_id": row["step_id"],
        "run_id": row["run_id"],
        "artifact_id": row["artifact_id"],
        "deployment_id": row["deployment_id"],
        "sequence": row["sequence"],
        "type": row["type"],
        "payload_json": payload,
        "payload": payload,
        "created_at": row["created_at"],
    }


def _payload_message_id(event: dict[str, object]) -> str | None:
    payload = event.get("payload_json")
    if not isinstance(payload, dict):
        return None
    value = payload.get("message_id")
    return value if isinstance(value, str) else None
