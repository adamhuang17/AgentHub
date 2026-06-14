from __future__ import annotations

import json
import uuid
from sqlite3 import Connection, Row

from services.api.app.agent_runs.schema import validate_event_type, validate_source_pairing
from services.api.app.agents.repository import get_agents_by_ids
from services.api.app.execution.events import record_event
from services.api.app.shared.database import connect
from services.api.app.shared.errors import NotFoundError, ValidationError
from services.api.app.shared.time import utc_now


def create_message_run(
    *,
    source_message_id: str,
    target_agent_id: str,
    instruction: str,
    context_bundle: dict[str, object],
    workspace_ref: dict[str, object] | None,
    allowed_tools: list[str],
    expected_artifacts: list[dict[str, object]],
    test_run_id: str,
    context_summary: dict[str, object] | None = None,
    context_ref: dict[str, object] | None = None,
) -> dict[str, object]:
    validate_source_pairing(
        source_type="message",
        run_mode="direct_response",
        source_message_id=source_message_id,
        plan_step_id=None,
    )
    target_agent = _require_enabled_agent(target_agent_id)
    del target_agent, instruction, context_bundle, workspace_ref, allowed_tools, expected_artifacts

    run_id = f"run_{uuid.uuid4().hex}"
    now = utc_now()
    with connect() as connection:
        message = _message_row(connection, source_message_id, test_run_id=test_run_id)
        connection.execute(
            """
            INSERT INTO agent_runs (
                id, conversation_id, source_type, source_message_id,
                plan_step_id, target_agent_id, run_mode, status, error_code,
                test_run_id, created_at, updated_at
            )
            VALUES (?, ?, 'message', ?, NULL, ?, 'direct_response',
                'created', NULL, ?, ?, ?)
            """,
            (
                run_id,
                message["conversation_id"],
                source_message_id,
                target_agent_id,
                test_run_id,
                now,
                now,
            ),
        )
        _append_event(
            connection,
            run_id=run_id,
            conversation_id=message["conversation_id"],
            event_type="run_created",
            payload={
                "run_id": run_id,
                "status": "created",
                "context_summary": context_summary or {},
                "context_ref": context_ref or {},
            },
        )
        record_event(
            connection,
            conversation_id=message["conversation_id"],
            run_id=run_id,
            event_type="agent_run.created",
            payload={
                "run_id": run_id,
                "status": "created",
                "source_type": "message",
                "source_message_id": source_message_id,
                "target_agent_id": target_agent_id,
                "run_mode": "direct_response",
                "context_summary": context_summary or {},
                "context_ref": context_ref or {},
            },
        )
    return get_run(run_id, test_run_id=test_run_id)


def create_plan_step_run(
    *,
    plan_step_id: str,
    target_agent_id: str | None,
    source_message_id: str | None,
    instruction: str,
    context_bundle: dict[str, object],
    workspace_ref: dict[str, object] | None,
    allowed_tools: list[str],
    expected_artifacts: list[dict[str, object]],
    test_run_id: str,
    context_summary: dict[str, object] | None = None,
    context_ref: dict[str, object] | None = None,
) -> dict[str, object]:
    validate_source_pairing(
        source_type="plan_step",
        run_mode="planned_step",
        source_message_id=source_message_id,
        plan_step_id=plan_step_id,
    )
    del instruction, context_bundle, workspace_ref, allowed_tools, expected_artifacts

    run_id = f"run_{uuid.uuid4().hex}"
    now = utc_now()
    with connect() as connection:
        step = _plan_step_source_row(connection, plan_step_id, test_run_id=test_run_id)
        if step["status"] == "blocked" or step["blocked_reason"]:
            raise ValidationError("Blocked plan_step cannot create an AgentRun.", code="plan_step_blocked")
        assigned_agent_id = step["assigned_agent_id"]
        if not assigned_agent_id:
            raise ValidationError(
                "planned_step run requires plan_step.assigned_agent_id.",
                code="plan_step_missing_assignee",
            )
        if target_agent_id is not None and target_agent_id != assigned_agent_id:
            raise ValidationError(
                "planned_step target_agent_id must match plan_step.assigned_agent_id.",
                code="plan_step_target_mismatch",
            )
        _require_enabled_agent(str(assigned_agent_id))
        original_message_id = source_message_id or step["created_by_message_id"]
        connection.execute(
            """
            INSERT INTO agent_runs (
                id, conversation_id, source_type, source_message_id,
                plan_step_id, target_agent_id, run_mode, status, error_code,
                test_run_id, created_at, updated_at
            )
            VALUES (?, ?, 'plan_step', ?, ?, ?, 'planned_step',
                'created', NULL, ?, ?, ?)
            """,
            (
                run_id,
                step["conversation_id"],
                original_message_id,
                plan_step_id,
                assigned_agent_id,
                test_run_id,
                now,
                now,
            ),
        )
        _append_event(
            connection,
            run_id=run_id,
            conversation_id=step["conversation_id"],
            event_type="run_created",
            payload={
                "run_id": run_id,
                "status": "created",
                "context_summary": context_summary or {},
                "context_ref": context_ref or {},
            },
        )
        record_event(
            connection,
            conversation_id=step["conversation_id"],
            task_id=step["task_id"],
            plan_id=step["plan_id"],
            step_id=plan_step_id,
            run_id=run_id,
            event_type="agent_run.created",
            payload={
                "run_id": run_id,
                "status": "created",
                "source_type": "plan_step",
                "source_message_id": original_message_id,
                "plan_step_id": plan_step_id,
                "target_agent_id": assigned_agent_id,
                "run_mode": "planned_step",
                "context_summary": context_summary or {},
                "context_ref": context_ref or {},
            },
        )
    return get_run(run_id, test_run_id=test_run_id)


def get_run(run_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM agent_runs WHERE id = ? AND test_run_id = ?",
            (run_id, test_run_id),
        ).fetchone()
    if row is None:
        raise NotFoundError("AgentRun not found.")
    return _run_from_row(row)


def prepare_plan_step_retry(plan_step_id: str, *, test_run_id: str) -> None:
    now = utc_now()
    with connect() as connection:
        step = _plan_step_source_row(connection, plan_step_id, test_run_id=test_run_id)
        connection.execute(
            """
            UPDATE plan_steps
            SET status = 'assigned', blocked_reason = NULL
            WHERE id = ?
            """,
            (plan_step_id,),
        )
        record_event(
            connection,
            conversation_id=step["conversation_id"],
            task_id=step["task_id"],
            plan_id=step["plan_id"],
            step_id=plan_step_id,
            event_type="step.retry_requested",
            payload={
                "task_id": step["task_id"],
                "plan_id": step["plan_id"],
                "step_id": plan_step_id,
                "status": "assigned",
            },
            created_at=now,
        )
        _refresh_linked_task_and_plan_status(
            connection,
            conversation_id=step["conversation_id"],
            task_id=step["task_id"],
            plan_id=step["plan_id"],
            now=now,
        )


def mark_run_started(run_id: str, *, test_run_id: str) -> dict[str, object]:
    now = utc_now()
    with connect() as connection:
        run = _run_row(connection, run_id, test_run_id=test_run_id)
        connection.execute(
            """
            UPDATE agent_runs
            SET status = 'running', updated_at = ?
            WHERE id = ? AND test_run_id = ?
            """,
            (now, run_id, test_run_id),
        )
        _append_event(
            connection,
            run_id=run_id,
            conversation_id=run["conversation_id"],
            event_type="run_started",
            payload={"run_id": run_id, "status": "running"},
        )
        links = _run_trace_links(connection, run)
        record_event(
            connection,
            conversation_id=run["conversation_id"],
            task_id=links["task_id"],
            plan_id=links["plan_id"],
            step_id=links["step_id"],
            run_id=run_id,
            event_type="agent_run.started",
            payload={"run_id": run_id, "status": "running"},
        )
        _mark_linked_plan_step(connection, links, run, status="running", run_id=run_id)
    return get_run(run_id, test_run_id=test_run_id)


def append_run_event(
    run_id: str,
    *,
    event_type: str,
    payload: dict[str, object],
    test_run_id: str,
) -> dict[str, object]:
    with connect() as connection:
        run = _run_row(connection, run_id, test_run_id=test_run_id)
        return _append_event(
            connection,
            run_id=run_id,
            conversation_id=run["conversation_id"],
            event_type=event_type,
            payload=payload,
        )


def fail_run(
    run_id: str,
    *,
    error_code: str,
    payload: dict[str, object],
    test_run_id: str,
) -> dict[str, object]:
    now = utc_now()
    with connect() as connection:
        run = _run_row(connection, run_id, test_run_id=test_run_id)
        connection.execute(
            """
            UPDATE agent_runs
            SET status = 'failed', error_code = ?, updated_at = ?
            WHERE id = ? AND test_run_id = ?
            """,
            (error_code, now, run_id, test_run_id),
        )
        _append_event(
            connection,
            run_id=run_id,
            conversation_id=run["conversation_id"],
            event_type="run_failed",
            payload=payload,
        )
        links = _run_trace_links(connection, run)
        record_event(
            connection,
            conversation_id=run["conversation_id"],
            task_id=links["task_id"],
            plan_id=links["plan_id"],
            step_id=links["step_id"],
            run_id=run_id,
            event_type="agent_run.failed",
            payload={
                **payload,
                "run_id": run_id,
                "status": "failed",
                "error_code": error_code,
            },
        )
        _mark_linked_plan_step(
            connection,
            links,
            run,
            status="failed",
            run_id=run_id,
            blocked_reason=error_code,
        )
    return get_run(run_id, test_run_id=test_run_id)


def mark_run_content_issue(
    run_id: str,
    *,
    status: str,
    error_code: str,
    payload: dict[str, object],
    test_run_id: str,
) -> dict[str, object]:
    if status not in {"incomplete", "final_content_empty"}:
        raise ValidationError("Unsupported content issue status.", code="agent_run_invalid_status")
    now = utc_now()
    with connect() as connection:
        run = _run_row(connection, run_id, test_run_id=test_run_id)
        connection.execute(
            """
            UPDATE agent_runs
            SET status = ?, error_code = ?, updated_at = ?
            WHERE id = ? AND test_run_id = ?
            """,
            (status, error_code, now, run_id, test_run_id),
        )
        terminal_payload = {
            **payload,
            "run_id": run_id,
            "status": status,
            "error_code": error_code,
        }
        _append_event(
            connection,
            run_id=run_id,
            conversation_id=run["conversation_id"],
            event_type="run_failed",
            payload=terminal_payload,
        )
        links = _run_trace_links(connection, run)
        record_event(
            connection,
            conversation_id=run["conversation_id"],
            task_id=links["task_id"],
            plan_id=links["plan_id"],
            step_id=links["step_id"],
            run_id=run_id,
            event_type="agent_run.failed",
            payload=terminal_payload,
        )
        _mark_linked_plan_step(
            connection,
            links,
            run,
            status="failed",
            run_id=run_id,
            blocked_reason=error_code,
        )
    return get_run(run_id, test_run_id=test_run_id)


def succeed_run(
    run_id: str,
    *,
    payload: dict[str, object],
    test_run_id: str,
) -> dict[str, object]:
    now = utc_now()
    with connect() as connection:
        run = _run_row(connection, run_id, test_run_id=test_run_id)
        connection.execute(
            """
            UPDATE agent_runs
            SET status = 'succeeded', error_code = NULL, updated_at = ?
            WHERE id = ? AND test_run_id = ?
            """,
            (now, run_id, test_run_id),
        )
        _append_event(
            connection,
            run_id=run_id,
            conversation_id=run["conversation_id"],
            event_type="run_succeeded",
            payload=payload,
        )
        links = _run_trace_links(connection, run)
        record_event(
            connection,
            conversation_id=run["conversation_id"],
            task_id=links["task_id"],
            plan_id=links["plan_id"],
            step_id=links["step_id"],
            run_id=run_id,
            event_type="agent_run.succeeded",
            payload={
                **payload,
                "run_id": run_id,
                "status": "succeeded",
            },
        )
        _mark_linked_plan_step(connection, links, run, status="succeeded", run_id=run_id)
    return get_run(run_id, test_run_id=test_run_id)


def list_run_events(run_id: str, *, test_run_id: str) -> list[dict[str, object]]:
    with connect() as connection:
        _run_row(connection, run_id, test_run_id=test_run_id)
        rows = connection.execute(
            """
            SELECT *
            FROM agent_run_events
            WHERE run_id = ?
            ORDER BY sequence ASC
            """,
            (run_id,),
        ).fetchall()
    return [_event_from_row(row) for row in rows]


def _append_event(
    connection: Connection,
    *,
    run_id: str,
    conversation_id: str,
    event_type: str,
    payload: dict[str, object],
) -> dict[str, object]:
    validate_event_type(event_type)
    row = connection.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM agent_run_events WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    sequence = int(row["next_sequence"])
    event_id = f"event_{uuid.uuid4().hex}"
    created_at = utc_now()
    connection.execute(
        """
        INSERT INTO agent_run_events (
            id, run_id, conversation_id, sequence, type, payload_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            run_id,
            conversation_id,
            sequence,
            event_type,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            created_at,
        ),
    )
    return {
        "id": event_id,
        "run_id": run_id,
        "conversation_id": conversation_id,
        "sequence": sequence,
        "type": event_type,
        "payload": payload,
        "payload_json": payload,
        "created_at": created_at,
    }


def _message_row(connection: Connection, message_id: str, *, test_run_id: str) -> Row:
    row = connection.execute(
        "SELECT * FROM messages WHERE id = ? AND test_run_id = ?",
        (message_id, test_run_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("Message not found.")
    return row


def _plan_step_source_row(connection: Connection, plan_step_id: str, *, test_run_id: str) -> Row:
    row = connection.execute(
        """
        SELECT
            ps.*,
            p.id AS plan_id,
            t.id AS task_id,
            t.conversation_id,
            t.created_by_message_id
        FROM plan_steps ps
        JOIN plans p ON p.id = ps.plan_id
        JOIN tasks t ON t.id = p.task_id
        WHERE ps.id = ? AND t.test_run_id = ?
        """,
        (plan_step_id, test_run_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("Plan step not found.")
    return row


def _run_trace_links(connection: Connection, run: Row) -> dict[str, str | None]:
    plan_step_id = run["plan_step_id"]
    if plan_step_id is None:
        return {"task_id": None, "plan_id": None, "step_id": None}
    row = connection.execute(
        """
        SELECT
            t.id AS task_id,
            p.id AS plan_id,
            ps.id AS step_id
        FROM plan_steps ps
        JOIN plans p ON p.id = ps.plan_id
        JOIN tasks t ON t.id = p.task_id
        WHERE ps.id = ?
        """,
        (plan_step_id,),
    ).fetchone()
    if row is None:
        return {"task_id": None, "plan_id": None, "step_id": plan_step_id}
    return {
        "task_id": row["task_id"],
        "plan_id": row["plan_id"],
        "step_id": row["step_id"],
    }


def _mark_linked_plan_step(
    connection: Connection,
    links: dict[str, str | None],
    run: Row,
    *,
    status: str,
    run_id: str,
    blocked_reason: str | None = None,
) -> None:
    step_id = links.get("step_id")
    task_id = links.get("task_id")
    plan_id = links.get("plan_id")
    if not step_id or not task_id or not plan_id:
        return
    connection.execute(
        """
        UPDATE plan_steps
        SET status = ?, blocked_reason = ?
        WHERE id = ?
        """,
        (status, blocked_reason, step_id),
    )
    event_type = {
        "running": "step.started",
        "succeeded": "step.succeeded",
        "failed": "step.failed",
    }.get(status, "step.updated")
    now = utc_now()
    record_event(
        connection,
        conversation_id=run["conversation_id"],
        task_id=task_id,
        plan_id=plan_id,
        step_id=step_id,
        run_id=run_id,
        event_type=event_type,
        payload={
            "task_id": task_id,
            "plan_id": plan_id,
            "step_id": step_id,
            "run_id": run_id,
            "status": status,
            "blocked_reason": blocked_reason,
        },
        created_at=now,
    )
    _refresh_linked_task_and_plan_status(
        connection,
        conversation_id=run["conversation_id"],
        task_id=task_id,
        plan_id=plan_id,
        now=now,
    )


def _refresh_linked_task_and_plan_status(
    connection: Connection,
    *,
    conversation_id: str,
    task_id: str,
    plan_id: str,
    now: str,
) -> None:
    rows = connection.execute(
        "SELECT status FROM plan_steps WHERE plan_id = ? ORDER BY rowid ASC",
        (plan_id,),
    ).fetchall()
    statuses = [str(row["status"]) for row in rows]
    if not statuses:
        return
    if any(status in {"failed", "incomplete", "final_content_empty"} for status in statuses):
        aggregate = "failed"
    elif any(status in {"running", "assigned"} for status in statuses):
        aggregate = "running"
    elif all(status == "succeeded" for status in statuses):
        aggregate = "succeeded"
    else:
        aggregate = "planned"
    connection.execute("UPDATE tasks SET status = ? WHERE id = ?", (aggregate, task_id))
    connection.execute("UPDATE plans SET status = ? WHERE id = ?", (aggregate if aggregate != "planned" else "ready", plan_id))
    record_event(
        connection,
        conversation_id=conversation_id,
        task_id=task_id,
        plan_id=plan_id,
        event_type="task.status_updated",
        payload={"task_id": task_id, "plan_id": plan_id, "status": aggregate},
        created_at=now,
    )


def _run_row(connection: Connection, run_id: str, *, test_run_id: str) -> Row:
    row = connection.execute(
        "SELECT * FROM agent_runs WHERE id = ? AND test_run_id = ?",
        (run_id, test_run_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("AgentRun not found.")
    return row


def _require_enabled_agent(agent_id: str) -> dict[str, object]:
    agents = get_agents_by_ids([agent_id])
    if not agents:
        raise ValidationError(f"Unknown target agent: {agent_id}", code="unknown_agent")
    agent = agents[0]
    if not agent["enabled"]:
        raise ValidationError(f"Target agent is disabled: {agent_id}", code="agent_disabled")
    return agent


def _run_from_row(row: Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "source_type": row["source_type"],
        "source_message_id": row["source_message_id"],
        "plan_step_id": row["plan_step_id"],
        "target_agent_id": row["target_agent_id"],
        "run_mode": row["run_mode"],
        "status": row["status"],
        "error_code": row["error_code"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _event_from_row(row: Row) -> dict[str, object]:
    payload = json.loads(row["payload_json"])
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "conversation_id": row["conversation_id"],
        "sequence": row["sequence"],
        "type": row["type"],
        "payload": payload,
        "payload_json": payload,
        "created_at": row["created_at"],
    }
