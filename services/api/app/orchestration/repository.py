from __future__ import annotations

import json
import uuid
from sqlite3 import Row

from services.api.app.orchestration.planner import PlanStepDraft
from services.api.app.execution.events import list_task_events, record_event
from services.api.app.shared.database import connect
from services.api.app.shared.errors import NotFoundError, ValidationError
from services.api.app.shared.time import utc_now


def create_mention_task(
    *,
    conversation_id: str,
    message_id: str,
    goal: str,
    agent_ids: list[str],
    dispatch_reasons: dict[str, str],
    test_run_id: str,
) -> dict[str, object]:
    if not agent_ids:
        raise ValidationError("At least one mentioned agent is required.")

    task_id = f"task_{uuid.uuid4().hex}"
    plan_id = f"plan_{uuid.uuid4().hex}"
    now = utc_now()
    step_ids: list[str] = []
    with connect() as connection:
        conversation = connection.execute(
            "SELECT id FROM conversations WHERE id = ? AND test_run_id = ?",
            (conversation_id, test_run_id),
        ).fetchone()
        if conversation is None:
            raise NotFoundError("Conversation not found.")

        message = connection.execute(
            """
            SELECT id
            FROM messages
            WHERE id = ? AND conversation_id = ? AND test_run_id = ?
            """,
            (message_id, conversation_id, test_run_id),
        ).fetchone()
        if message is None:
            raise NotFoundError("Message not found.")

        connection.execute(
            """
            INSERT INTO tasks (
                id, conversation_id, created_by_message_id, goal,
                status, test_run_id, created_at
            )
            VALUES (?, ?, ?, ?, 'planned', ?, ?)
            """,
            (task_id, conversation_id, message_id, goal, test_run_id, now),
        )
        record_event(
            connection,
            conversation_id=conversation_id,
            task_id=task_id,
            event_type="task.created",
            payload={
                "task_id": task_id,
                "created_by_message_id": message_id,
                "goal": goal,
                "status": "planned",
            },
            created_at=now,
        )
        connection.execute(
            """
            INSERT INTO plans (id, task_id, version, status, test_run_id, created_at)
            VALUES (?, ?, 1, 'ready', ?, ?)
            """,
            (plan_id, task_id, test_run_id, now),
        )
        record_event(
            connection,
            conversation_id=conversation_id,
            task_id=task_id,
            plan_id=plan_id,
            event_type="plan.created",
            payload={
                "task_id": task_id,
                "plan_id": plan_id,
                "version": 1,
                "status": "ready",
            },
            created_at=now,
        )
        for agent_id in agent_ids:
            step_id = f"step_{uuid.uuid4().hex}"
            step_ids.append(step_id)
            connection.execute(
                """
                INSERT INTO plan_steps (
                    id, plan_id, kind, assigned_agent_id, status,
                    dispatch_source, dispatch_reason, blocked_reason, depends_on_json,
                    expected_output_json, created_at
                )
                VALUES (?, ?, 'agent_message', ?, 'assigned', 'mention', ?, NULL, '[]', '{}', ?)
                """,
                (step_id, plan_id, agent_id, dispatch_reasons[agent_id], now),
            )
            record_event(
                connection,
                conversation_id=conversation_id,
                task_id=task_id,
                plan_id=plan_id,
                step_id=step_id,
                event_type="step.created",
                payload={
                    "task_id": task_id,
                    "plan_id": plan_id,
                    "step_id": step_id,
                    "kind": "agent_message",
                    "assigned_agent_id": agent_id,
                    "status": "assigned",
                    "dispatch_source": "mention",
                    "dispatch_reason": dispatch_reasons[agent_id],
                    "blocked_reason": None,
                },
                created_at=now,
            )

    return get_task(task_id, test_run_id=test_run_id)


def create_planned_task(
    *,
    conversation_id: str,
    message_id: str,
    goal: str,
    steps: list[PlanStepDraft],
    test_run_id: str,
) -> dict[str, object]:
    if not steps:
        raise ValidationError("At least one planned step is required.")

    task_id = f"task_{uuid.uuid4().hex}"
    plan_id = f"plan_{uuid.uuid4().hex}"
    now = utc_now()
    step_ids = [f"step_{uuid.uuid4().hex}" for _ in steps]
    with connect() as connection:
        conversation = connection.execute(
            "SELECT id FROM conversations WHERE id = ? AND test_run_id = ?",
            (conversation_id, test_run_id),
        ).fetchone()
        if conversation is None:
            raise NotFoundError("Conversation not found.")

        message = connection.execute(
            """
            SELECT id
            FROM messages
            WHERE id = ? AND conversation_id = ? AND test_run_id = ?
            """,
            (message_id, conversation_id, test_run_id),
        ).fetchone()
        if message is None:
            raise NotFoundError("Message not found.")

        connection.execute(
            """
            INSERT INTO tasks (
                id, conversation_id, created_by_message_id, goal,
                status, test_run_id, created_at
            )
            VALUES (?, ?, ?, ?, 'planned', ?, ?)
            """,
            (task_id, conversation_id, message_id, goal, test_run_id, now),
        )
        record_event(
            connection,
            conversation_id=conversation_id,
            task_id=task_id,
            event_type="task.created",
            payload={
                "task_id": task_id,
                "created_by_message_id": message_id,
                "goal": goal,
                "status": "planned",
            },
            created_at=now,
        )
        connection.execute(
            """
            INSERT INTO plans (id, task_id, version, status, test_run_id, created_at)
            VALUES (?, ?, 1, 'ready', ?, ?)
            """,
            (plan_id, task_id, test_run_id, now),
        )
        record_event(
            connection,
            conversation_id=conversation_id,
            task_id=task_id,
            plan_id=plan_id,
            event_type="plan.created",
            payload={
                "task_id": task_id,
                "plan_id": plan_id,
                "version": 1,
                "status": "ready",
            },
            created_at=now,
        )
        step_key_to_id = {f"step-{index + 1}": step_id for index, step_id in enumerate(step_ids)}
        for step, step_id in zip(steps, step_ids):
            step_key_to_id[step.external_id] = step_id
        for index, step in enumerate(steps):
            depends_on = _resolve_step_dependencies(step.depends_on, step_key_to_id)
            connection.execute(
                """
                INSERT INTO plan_steps (
                    id, plan_id, kind, assigned_agent_id, status,
                    dispatch_source, dispatch_reason, blocked_reason,
                    depends_on_json, expected_output_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step_ids[index],
                    plan_id,
                    step.kind,
                    step.assigned_agent_id,
                    step.status,
                    step.dispatch_source,
                    step.dispatch_reason,
                    step.blocked_reason,
                    json.dumps(depends_on, separators=(",", ":")),
                    json.dumps(step.expected_output, separators=(",", ":")),
                    now,
                ),
            )
            record_event(
                connection,
                conversation_id=conversation_id,
                task_id=task_id,
                plan_id=plan_id,
                step_id=step_ids[index],
                event_type="step.created",
                payload={
                    "task_id": task_id,
                    "plan_id": plan_id,
                    "step_id": step_ids[index],
                    "kind": step.kind,
                    "assigned_agent_id": step.assigned_agent_id,
                    "status": step.status,
                    "dispatch_source": step.dispatch_source,
                    "dispatch_reason": step.dispatch_reason,
                    "blocked_reason": step.blocked_reason,
                    "depends_on": depends_on,
                    "external_id": step.external_id,
                    "title": step.title,
                    "instruction": step.instruction,
                    "expected_output": step.expected_output,
                },
                created_at=now,
            )
            if step.status == "blocked":
                record_event(
                    connection,
                    conversation_id=conversation_id,
                    task_id=task_id,
                    plan_id=plan_id,
                    step_id=step_ids[index],
                    event_type="step.blocked",
                    payload={
                        "task_id": task_id,
                        "plan_id": plan_id,
                        "step_id": step_ids[index],
                        "kind": step.kind,
                        "blocked_reason": step.blocked_reason,
                        "dispatch_reason": step.dispatch_reason,
                    },
                    created_at=now,
                )

    return get_task(task_id, test_run_id=test_run_id)


def _resolve_step_dependencies(depends_on: list[str], step_key_to_id: dict[str, str]) -> list[str]:
    resolved: list[str] = []
    for dependency in depends_on:
        step_id = step_key_to_id.get(dependency)
        if step_id is None:
            raise ValidationError(f"Unknown planner step dependency: {dependency}")
        resolved.append(step_id)
    return resolved


def list_tasks_for_conversation(conversation_id: str, *, test_run_id: str) -> list[dict[str, object]]:
    with connect() as connection:
        conversation = connection.execute(
            "SELECT id FROM conversations WHERE id = ? AND test_run_id = ?",
            (conversation_id, test_run_id),
        ).fetchone()
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        rows = connection.execute(
            """
            SELECT *
            FROM tasks
            WHERE conversation_id = ? AND test_run_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_id, test_run_id),
        ).fetchall()
    return [_task_from_row(row) for row in rows]


def get_task(task_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ? AND test_run_id = ?",
            (task_id, test_run_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Task not found.")
        task = _task_from_row(row)
        plan_row = connection.execute(
            """
            SELECT *
            FROM plans
            WHERE task_id = ? AND test_run_id = ?
            ORDER BY version DESC, created_at DESC
            LIMIT 1
            """,
            (task_id, test_run_id),
        ).fetchone()
        if plan_row is not None:
            plan = _plan_from_row(plan_row)
            steps = _list_steps_for_plan(connection, plan["id"])
            plan["steps"] = steps
            task["plan"] = plan
            task["steps"] = steps
        task["runs"] = _list_runs_for_task(connection, task_id, test_run_id=test_run_id)
    events = list_task_events(task_id, test_run_id=test_run_id)
    task["events"] = events
    task["event_summary"] = _event_summary(events)
    return task


def get_plan_for_task(task_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        task = connection.execute(
            "SELECT id FROM tasks WHERE id = ? AND test_run_id = ?",
            (task_id, test_run_id),
        ).fetchone()
        if task is None:
            raise NotFoundError("Task not found.")
        row = connection.execute(
            """
            SELECT *
            FROM plans
            WHERE task_id = ? AND test_run_id = ?
            ORDER BY version DESC, created_at DESC
            LIMIT 1
            """,
            (task_id, test_run_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Plan not found.")
        plan = _plan_from_row(row)
        plan["steps"] = _list_steps_for_plan(connection, plan["id"])
    return plan


def get_plan(plan_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM plans WHERE id = ? AND test_run_id = ?",
            (plan_id, test_run_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Plan not found.")
        plan = _plan_from_row(row)
        plan["steps"] = _list_steps_for_plan(connection, plan_id)
    return plan


def mark_plan_step_running(
    step_id: str,
    *,
    test_run_id: str,
    run_id: str | None = None,
) -> dict[str, object]:
    return _mark_plan_step_execution_state(step_id, status="running", test_run_id=test_run_id, run_id=run_id)


def mark_plan_step_succeeded(
    step_id: str,
    *,
    test_run_id: str,
    run_id: str | None = None,
) -> dict[str, object]:
    return _mark_plan_step_execution_state(step_id, status="succeeded", test_run_id=test_run_id, run_id=run_id)


def mark_plan_step_failed(
    step_id: str,
    *,
    test_run_id: str,
    run_id: str | None = None,
    error_code: str | None = None,
) -> dict[str, object]:
    return _mark_plan_step_execution_state(
        step_id,
        status="failed",
        test_run_id=test_run_id,
        run_id=run_id,
        blocked_reason=error_code or "agent_run_failed",
    )


def _mark_plan_step_execution_state(
    step_id: str,
    *,
    status: str,
    test_run_id: str,
    run_id: str | None = None,
    blocked_reason: str | None = None,
) -> dict[str, object]:
    now = utc_now()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT
                ps.id AS step_id,
                ps.plan_id,
                t.id AS task_id,
                t.conversation_id
            FROM plan_steps ps
            JOIN plans p ON p.id = ps.plan_id
            JOIN tasks t ON t.id = p.task_id
            WHERE ps.id = ? AND t.test_run_id = ?
            """,
            (step_id, test_run_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Plan step not found.")

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
        record_event(
            connection,
            conversation_id=row["conversation_id"],
            task_id=row["task_id"],
            plan_id=row["plan_id"],
            step_id=step_id,
            run_id=run_id,
            event_type=event_type,
            payload={
                "task_id": row["task_id"],
                "plan_id": row["plan_id"],
                "step_id": step_id,
                "run_id": run_id,
                "status": status,
                "blocked_reason": blocked_reason,
            },
            created_at=now,
        )
        _refresh_task_and_plan_status(connection, task_id=row["task_id"], plan_id=row["plan_id"], now=now)
    return get_task(str(row["task_id"]), test_run_id=test_run_id)


def _refresh_task_and_plan_status(connection, *, task_id: str, plan_id: str, now: str) -> None:
    rows = connection.execute(
        "SELECT status FROM plan_steps WHERE plan_id = ? ORDER BY rowid ASC",
        (plan_id,),
    ).fetchall()
    statuses = [str(row["status"]) for row in rows]
    if not statuses:
        return
    if any(status == "failed" for status in statuses):
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
        conversation_id=_conversation_id_for_task(connection, task_id),
        task_id=task_id,
        plan_id=plan_id,
        event_type="task.status_updated",
        payload={"task_id": task_id, "plan_id": plan_id, "status": aggregate},
        created_at=now,
    )


def _conversation_id_for_task(connection, task_id: str) -> str:
    row = connection.execute("SELECT conversation_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise NotFoundError("Task not found.")
    return str(row["conversation_id"])


def _list_steps_for_plan(connection, plan_id: str) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT *
        FROM plan_steps
        WHERE plan_id = ?
        ORDER BY rowid ASC
        """,
        (plan_id,),
    ).fetchall()
    return [_step_from_row(row) for row in rows]


def _list_runs_for_task(connection, task_id: str, *, test_run_id: str) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT ar.*
        FROM agent_runs ar
        JOIN plan_steps ps ON ps.id = ar.plan_step_id
        JOIN plans p ON p.id = ps.plan_id
        JOIN tasks t ON t.id = p.task_id
        WHERE t.id = ? AND t.test_run_id = ? AND ar.test_run_id = ?
        ORDER BY ar.created_at ASC, ar.id ASC
        """,
        (task_id, test_run_id, test_run_id),
    ).fetchall()
    return [_run_from_row(row) for row in rows]


def _event_summary(events: list[dict[str, object]]) -> dict[str, object]:
    type_counts: dict[str, int] = {}
    for event in events:
        event_type = str(event["type"])
        type_counts[event_type] = type_counts.get(event_type, 0) + 1
    return {
        "count": len(events),
        "last_sequence": events[-1]["sequence"] if events else None,
        "types": type_counts,
    }


def _task_from_row(row: Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "created_by_message_id": row["created_by_message_id"],
        "goal": row["goal"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _plan_from_row(row: Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "version": row["version"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _step_from_row(row: Row) -> dict[str, object]:
    expected_output = json.loads(row["expected_output_json"])
    return {
        "id": row["id"],
        "plan_id": row["plan_id"],
        "kind": row["kind"],
        "external_id": expected_output.get("step_id"),
        "title": expected_output.get("title"),
        "instruction": expected_output.get("instruction"),
        "assigned_agent_id": row["assigned_agent_id"],
        "status": row["status"],
        "dispatch_source": row["dispatch_source"],
        "dispatch_reason": row["dispatch_reason"],
        "blocked_reason": row["blocked_reason"],
        "depends_on": json.loads(row["depends_on_json"]),
        "expected_output": expected_output,
        "created_at": row["created_at"],
    }


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
