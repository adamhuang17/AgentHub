from __future__ import annotations

import hashlib
import json
import uuid
from sqlite3 import Connection, Row

from services.api.app.shared.database import connect
from services.api.app.shared.time import utc_now


def ensure_audit_log_table(connection: Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id TEXT PRIMARY KEY,
            actor_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            test_run_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_audit_logs_target
            ON audit_logs(test_run_id, target_type, target_id, created_at ASC);
        CREATE INDEX IF NOT EXISTS idx_audit_logs_action
            ON audit_logs(test_run_id, action_type, created_at ASC);
        """
    )


def payload_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def create_audit_log(
    *,
    actor_type: str,
    actor_id: str,
    action_type: str,
    target_type: str,
    target_id: str,
    payload: dict[str, object],
    test_run_id: str,
) -> dict[str, object]:
    with connect() as connection:
        ensure_audit_log_table(connection)
        return record_audit_log(
            connection,
            actor_type=actor_type,
            actor_id=actor_id,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            payload=payload,
            test_run_id=test_run_id,
        )


def record_audit_log(
    connection: Connection,
    *,
    actor_type: str,
    actor_id: str,
    action_type: str,
    target_type: str,
    target_id: str,
    payload: dict[str, object],
    test_run_id: str,
) -> dict[str, object]:
    ensure_audit_log_table(connection)
    audit_log = {
        "id": f"audit_{uuid.uuid4().hex}",
        "actor_type": _required(actor_type, "actor_type"),
        "actor_id": _required(actor_id, "actor_id"),
        "action_type": _required(action_type, "action_type"),
        "target_type": _required(target_type, "target_type"),
        "target_id": _required(target_id, "target_id"),
        "payload_hash": payload_hash(payload),
        "created_at": utc_now(),
    }
    connection.execute(
        """
        INSERT INTO audit_logs (
            id, actor_type, actor_id, action_type, target_type,
            target_id, payload_hash, test_run_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_log["id"],
            audit_log["actor_type"],
            audit_log["actor_id"],
            audit_log["action_type"],
            audit_log["target_type"],
            audit_log["target_id"],
            audit_log["payload_hash"],
            test_run_id,
            audit_log["created_at"],
        ),
    )
    return audit_log


def list_audit_logs(
    *,
    test_run_id: str,
    action_type: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
) -> list[dict[str, object]]:
    filters = ["test_run_id = ?"]
    params: list[object] = [test_run_id]
    if action_type is not None:
        filters.append("action_type = ?")
        params.append(action_type)
    if target_type is not None:
        filters.append("target_type = ?")
        params.append(target_type)
    if target_id is not None:
        filters.append("target_id = ?")
        params.append(target_id)

    with connect() as connection:
        ensure_audit_log_table(connection)
        rows = connection.execute(
            f"""
            SELECT *
            FROM audit_logs
            WHERE {" AND ".join(filters)}
            ORDER BY created_at ASC, id ASC
            """,
            params,
        ).fetchall()
    return [_audit_log_from_row(row) for row in rows]


def _audit_log_from_row(row: Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "actor_type": row["actor_type"],
        "actor_id": row["actor_id"],
        "action_type": row["action_type"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "payload_hash": row["payload_hash"],
        "created_at": row["created_at"],
    }


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip()
