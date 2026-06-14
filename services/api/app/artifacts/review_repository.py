from __future__ import annotations

import json
import uuid
from sqlite3 import Connection, Row

from services.api.app.artifacts.repository import _ensure_artifact_tables
from services.api.app.artifacts.schema import (
    PATCH_APPLICATION_STATUSES,
    REVIEW_DECISIONS,
    REVIEW_REQUEST_STATUSES,
)
from services.api.app.execution.events import record_event
from services.api.app.permissions import audit_repository
from services.api.app.shared.database import connect
from services.api.app.shared.errors import NotFoundError, ValidationError
from services.api.app.shared.time import utc_now


def create_review_request(
    *,
    conversation_id: str,
    artifact_id: str,
    payload: dict[str, object],
    test_run_id: str,
) -> dict[str, object]:
    request_id = f"revreq_{uuid.uuid4().hex}"
    now = utc_now()
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    with connect() as connection:
        _ensure_artifact_tables(connection)
        audit_repository.ensure_audit_log_table(connection)
        _validate_artifact(connection, artifact_id, conversation_id=conversation_id, test_run_id=test_run_id)
        connection.execute(
            """
            INSERT INTO review_requests (
                id, conversation_id, artifact_id, action_type, status,
                payload_json, test_run_id, created_at
            )
            VALUES (?, ?, ?, 'apply_patch', 'pending', ?, ?, ?)
            """,
            (request_id, conversation_id, artifact_id, payload_json, test_run_id, now),
        )
        audit_log = audit_repository.record_audit_log(
            connection,
            actor_type="system",
            actor_id="agenthub",
            action_type="review_request.created",
            target_type="review_request",
            target_id=request_id,
            payload={
                "conversation_id": conversation_id,
                "artifact_id": artifact_id,
                "action_type": "apply_patch",
                "status": "pending",
                "payload_json": payload_json,
            },
            test_run_id=test_run_id,
        )
        record_event(
            connection,
            conversation_id=conversation_id,
            artifact_id=artifact_id,
            event_type="review_request.created",
            payload={
                "review_request_id": request_id,
                "artifact_id": artifact_id,
                "action_type": "apply_patch",
                "status": "pending",
                "request_payload": payload,
            },
            created_at=now,
        )
    request = get_review_request(request_id, test_run_id=test_run_id)
    request["audit_log_id"] = audit_log["id"]
    return request


def list_review_requests(
    *,
    test_run_id: str,
    conversation_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, object]]:
    filters = ["test_run_id = ?"]
    params: list[object] = [test_run_id]
    if conversation_id is not None:
        filters.append("conversation_id = ?")
        params.append(conversation_id)
    if status is not None:
        if status not in REVIEW_REQUEST_STATUSES:
            raise ValidationError("Unsupported review request status.", code="review_request_invalid")
        filters.append("status = ?")
        params.append(status)

    with connect() as connection:
        _ensure_artifact_tables(connection)
        rows = connection.execute(
            f"""
            SELECT *
            FROM review_requests
            WHERE {" AND ".join(filters)}
            ORDER BY created_at ASC, id ASC
            """,
            params,
        ).fetchall()
    return [_review_request_from_row(row) for row in rows]


def get_review_request(request_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        _ensure_artifact_tables(connection)
        row = connection.execute(
            """
            SELECT *
            FROM review_requests
            WHERE id = ? AND test_run_id = ?
            """,
            (request_id, test_run_id),
        ).fetchone()
    if row is None:
        raise NotFoundError("ReviewRequest not found.")
    return _review_request_from_row(row)


def latest_review_request_for_artifact(artifact_id: str, *, test_run_id: str) -> dict[str, object] | None:
    with connect() as connection:
        _ensure_artifact_tables(connection)
        row = connection.execute(
            """
            SELECT *
            FROM review_requests
            WHERE artifact_id = ? AND action_type = 'apply_patch' AND test_run_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (artifact_id, test_run_id),
        ).fetchone()
    return _review_request_from_row(row) if row is not None else None


def create_review_decision(
    *,
    request_id: str,
    decision: str,
    decided_by: str,
    comment: str | None,
    test_run_id: str,
) -> dict[str, object]:
    if decision not in REVIEW_DECISIONS:
        raise ValidationError("Unsupported review decision.", code="review_decision_invalid")
    decision_id = f"revdec_{uuid.uuid4().hex}"
    now = utc_now()
    with connect() as connection:
        _ensure_artifact_tables(connection)
        audit_repository.ensure_audit_log_table(connection)
        request = _review_request_row(connection, request_id, test_run_id=test_run_id)
        if request["status"] != "pending":
            raise ValidationError("ReviewRequest has already been decided.", code="review_request_not_pending")
        connection.execute(
            """
            INSERT INTO review_decisions (
                id, request_id, decision, decided_by, comment, test_run_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (decision_id, request_id, decision, decided_by, comment, test_run_id, now),
        )
        connection.execute(
            """
            UPDATE review_requests
            SET status = ?
            WHERE id = ? AND test_run_id = ?
            """,
            (decision, request_id, test_run_id),
        )
        audit_log = audit_repository.record_audit_log(
            connection,
            actor_type="user",
            actor_id=decided_by,
            action_type=f"review_decision.{decision}",
            target_type="review_decision",
            target_id=decision_id,
            payload={
                "request_id": request_id,
                "decision": decision,
                "decided_by": decided_by,
                "comment": comment,
            },
            test_run_id=test_run_id,
        )
    result = get_review_decision(decision_id, test_run_id=test_run_id)
    result["audit_log_id"] = audit_log["id"]
    return result


def get_review_decision(decision_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        _ensure_artifact_tables(connection)
        row = connection.execute(
            """
            SELECT *
            FROM review_decisions
            WHERE id = ? AND test_run_id = ?
            """,
            (decision_id, test_run_id),
        ).fetchone()
    if row is None:
        raise NotFoundError("ReviewDecision not found.")
    return _review_decision_from_row(row)


def create_patch_application(
    *,
    patch_artifact_id: str | None,
    diff_artifact_id: str | None,
    target_artifact_id: str,
    base_version_id: str,
    result_version_id: str | None,
    status: str,
    error_code: str | None,
    test_run_id: str,
) -> dict[str, object]:
    if patch_artifact_id is None and diff_artifact_id is None:
        raise ValidationError("PatchApplication must reference a patch or diff artifact.", code="patch_application_invalid")
    if status not in PATCH_APPLICATION_STATUSES:
        raise ValidationError("Unsupported PatchApplication status.", code="patch_application_invalid")

    application_id = f"patchapp_{uuid.uuid4().hex}"
    now = utc_now()
    with connect() as connection:
        _ensure_artifact_tables(connection)
        audit_repository.ensure_audit_log_table(connection)
        artifact_context = _artifact_context(connection, target_artifact_id, test_run_id=test_run_id)
        connection.execute(
            """
            INSERT INTO patch_applications (
                id, patch_artifact_id, diff_artifact_id, target_artifact_id,
                base_version_id, result_version_id, status, error_code,
                test_run_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                patch_artifact_id,
                diff_artifact_id,
                target_artifact_id,
                base_version_id,
                result_version_id,
                status,
                error_code,
                test_run_id,
                now,
            ),
        )
        audit_log = audit_repository.record_audit_log(
            connection,
            actor_type="system",
            actor_id="agenthub",
            action_type=f"patch_application.{status}",
            target_type="patch_application",
            target_id=application_id,
            payload={
                "patch_artifact_id": patch_artifact_id,
                "diff_artifact_id": diff_artifact_id,
                "target_artifact_id": target_artifact_id,
                "base_version_id": base_version_id,
                "result_version_id": result_version_id,
                "status": status,
                "error_code": error_code,
            },
            test_run_id=test_run_id,
        )
        if status in {"applied", "failed", "conflict"}:
            record_event(
                connection,
                conversation_id=str(artifact_context["conversation_id"]),
                artifact_id=target_artifact_id,
                event_type=f"patch_application.{status}",
                payload={
                    "patch_application_id": application_id,
                    "patch_artifact_id": patch_artifact_id,
                    "diff_artifact_id": diff_artifact_id,
                    "target_artifact_id": target_artifact_id,
                    "base_version_id": base_version_id,
                    "result_version_id": result_version_id,
                    "status": status,
                    "error_code": error_code,
                },
                created_at=now,
            )
    application = get_patch_application(application_id, test_run_id=test_run_id)
    application["audit_log_id"] = audit_log["id"]
    return application


def latest_patch_application_for_source(
    *,
    patch_artifact_id: str | None,
    diff_artifact_id: str | None,
    target_artifact_id: str,
    base_version_id: str,
    statuses: set[str] | None,
    test_run_id: str,
) -> dict[str, object] | None:
    filters = ["target_artifact_id = ?", "base_version_id = ?", "test_run_id = ?"]
    params: list[object] = [target_artifact_id, base_version_id, test_run_id]
    if patch_artifact_id is not None:
        filters.append("patch_artifact_id = ?")
        params.append(patch_artifact_id)
    else:
        filters.append("patch_artifact_id IS NULL")
    if diff_artifact_id is not None:
        filters.append("diff_artifact_id = ?")
        params.append(diff_artifact_id)
    else:
        filters.append("diff_artifact_id IS NULL")
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        filters.append(f"status IN ({placeholders})")
        params.extend(sorted(statuses))

    with connect() as connection:
        _ensure_artifact_tables(connection)
        row = connection.execute(
            f"""
            SELECT *
            FROM patch_applications
            WHERE {" AND ".join(filters)}
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    if row is None:
        return None
    return _attach_patch_application_audit_log(_patch_application_from_row(row), test_run_id=test_run_id)


def get_patch_application(application_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        _ensure_artifact_tables(connection)
        row = connection.execute(
            """
            SELECT *
            FROM patch_applications
            WHERE id = ? AND test_run_id = ?
            """,
            (application_id, test_run_id),
        ).fetchone()
    if row is None:
        raise NotFoundError("PatchApplication not found.")
    return _attach_patch_application_audit_log(_patch_application_from_row(row), test_run_id=test_run_id)


def _validate_artifact(connection: Connection, artifact_id: str, *, conversation_id: str, test_run_id: str) -> None:
    row = connection.execute(
        """
        SELECT id
        FROM artifacts
        WHERE id = ? AND conversation_id = ? AND test_run_id = ?
        """,
        (artifact_id, conversation_id, test_run_id),
    ).fetchone()
    if row is None:
        raise ValidationError("ReviewRequest artifact must belong to the conversation.", code="review_request_invalid")


def _artifact_context(connection: Connection, artifact_id: str, *, test_run_id: str) -> Row:
    row = connection.execute(
        """
        SELECT id, conversation_id
        FROM artifacts
        WHERE id = ? AND test_run_id = ?
        """,
        (artifact_id, test_run_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("Artifact not found.")
    return row


def _review_request_row(connection: Connection, request_id: str, *, test_run_id: str) -> Row:
    row = connection.execute(
        """
        SELECT *
        FROM review_requests
        WHERE id = ? AND test_run_id = ?
        """,
        (request_id, test_run_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("ReviewRequest not found.")
    return row


def _review_request_from_row(row: Row) -> dict[str, object]:
    payload_json = row["payload_json"]
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "artifact_id": row["artifact_id"],
        "action_type": row["action_type"],
        "status": row["status"],
        "payload_json": payload_json,
        "payload": json.loads(payload_json),
        "created_at": row["created_at"],
    }


def _review_decision_from_row(row: Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "request_id": row["request_id"],
        "decision": row["decision"],
        "decided_by": row["decided_by"],
        "comment": row["comment"],
        "created_at": row["created_at"],
    }


def _patch_application_from_row(row: Row) -> dict[str, object]:
    result = {
        "id": row["id"],
        "patch_artifact_id": row["patch_artifact_id"],
        "diff_artifact_id": row["diff_artifact_id"],
        "target_artifact_id": row["target_artifact_id"],
        "base_version_id": row["base_version_id"],
        "result_version_id": row["result_version_id"],
        "status": row["status"],
        "error_code": row["error_code"],
        "created_at": row["created_at"],
    }
    if result["result_version_id"] is not None:
        result["new_version_id"] = result["result_version_id"]
    return result


def _attach_patch_application_audit_log(application: dict[str, object], *, test_run_id: str) -> dict[str, object]:
    logs = audit_repository.list_audit_logs(
        test_run_id=test_run_id,
        target_type="patch_application",
        target_id=str(application["id"]),
    )
    if logs:
        application["audit_log_id"] = logs[-1]["id"]
    return application
