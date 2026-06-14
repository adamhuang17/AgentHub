from __future__ import annotations

import hashlib
import uuid

from services.api.app.shared.database import connect
from services.api.app.shared.time import utc_now


def record_planner_trace(
    *,
    conversation_id: str,
    message_id: str,
    backend: str,
    model: str | None,
    decision_type: str | None,
    raw_output: str | None = None,
    raw_output_hash: str | None = None,
    error_code: str | None = None,
    test_run_id: str | None = None,
) -> str:
    trace_id = f"ptrace_{uuid.uuid4().hex}"
    digest = raw_output_hash
    if digest is None and raw_output is not None:
        digest = hashlib.sha256(raw_output.encode("utf-8")).hexdigest()
    with connect() as connection:
        _ensure_planner_trace_table(connection)
        connection.execute(
            """
            INSERT INTO planner_traces (
                trace_id, conversation_id, message_id, backend, model,
                decision_type, raw_output_hash, error_code, test_run_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                conversation_id,
                message_id,
                backend,
                model,
                decision_type,
                digest,
                error_code,
                test_run_id,
                utc_now(),
            ),
        )
    return trace_id


def list_planner_traces(
    *,
    conversation_id: str | None = None,
    message_id: str | None = None,
    test_run_id: str | None = None,
) -> list[dict[str, object]]:
    filters: list[str] = []
    params: list[object] = []
    if conversation_id is not None:
        filters.append("conversation_id = ?")
        params.append(conversation_id)
    if message_id is not None:
        filters.append("message_id = ?")
        params.append(message_id)
    if test_run_id is not None:
        filters.append("test_run_id = ?")
        params.append(test_run_id)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    with connect() as connection:
        _ensure_planner_trace_table(connection)
        rows = connection.execute(
            f"""
            SELECT *
            FROM planner_traces
            {where}
            ORDER BY created_at ASC, trace_id ASC
            """,
            params,
        ).fetchall()
    return [
        {
            "trace_id": row["trace_id"],
            "conversation_id": row["conversation_id"],
            "message_id": row["message_id"],
            "backend": row["backend"],
            "model": row["model"],
            "decision_type": row["decision_type"],
            "raw_output_hash": row["raw_output_hash"],
            "error_code": row["error_code"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _ensure_planner_trace_table(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS planner_traces (
            trace_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            backend TEXT NOT NULL,
            model TEXT,
            decision_type TEXT,
            raw_output_hash TEXT,
            error_code TEXT,
            test_run_id TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_planner_traces_message
            ON planner_traces(test_run_id, conversation_id, message_id, created_at ASC);
        """
    )
