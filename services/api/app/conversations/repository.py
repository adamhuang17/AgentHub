from __future__ import annotations

import json
import uuid
from contextlib import suppress
from pathlib import Path
from sqlite3 import Row

from services.api.app.artifacts.repository import artifact_cards_for_references, validate_artifact_references
from services.api.app.artifacts.store import artifact_store_root
from services.api.app.agents.repository import get_enabled_agents_by_ids
from services.api.app.execution.events import list_events, record_event
from services.api.app.shared.errors import NotFoundError, ValidationError
from services.api.app.shared.database import connect
from services.api.app.shared.time import utc_now


def create_conversation(
    *,
    title: str,
    mode: str,
    agent_ids: list[str],
    test_run_id: str,
) -> dict[str, object]:
    clean_title = title.strip()
    if not clean_title:
        raise ValidationError("Conversation title is required.")
    if not mode:
        raise ValidationError("Conversation mode is required.")

    selected_agents = get_enabled_agents_by_ids(agent_ids)
    if len(selected_agents) != len(set(agent_ids)):
        known_ids = {agent["id"] for agent in selected_agents}
        missing = [agent_id for agent_id in agent_ids if agent_id not in known_ids]
        raise ValidationError(f"Unknown or disabled agent ids: {missing}")

    conversation_id = f"conv_{uuid.uuid4().hex}"
    now = utc_now()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO conversations (
                id, title, mode, status, test_run_id, created_at,
                updated_at, last_active_at, archived_at
            )
            VALUES (?, ?, ?, 'active', ?, ?, ?, ?, NULL)
            """,
            (conversation_id, clean_title, mode, test_run_id, now, now, now),
        )
        _insert_member(connection, conversation_id, "user", "user", now)
        _insert_member(connection, conversation_id, "orchestrator", "orchestrator", now)
        for agent_id in dict.fromkeys(agent_ids):
            _insert_member(connection, conversation_id, "agent", agent_id, now)

    return get_conversation(conversation_id, test_run_id=test_run_id)


def list_conversations(
    *,
    test_run_id: str,
    query: str | None = None,
    archived: bool | None = None,
    include_archived: bool = False,
) -> list[dict[str, object]]:
    filters = ["test_run_id = ?"]
    params: list[object] = [test_run_id]

    if archived is True:
        filters.append("archived_at IS NOT NULL")
    elif archived is False or not include_archived:
        filters.append("archived_at IS NULL")

    if query:
        filters.append("LOWER(title) LIKE ?")
        params.append(f"%{query.lower()}%")

    where = " AND ".join(filters)
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM conversations
            WHERE {where}
            ORDER BY last_active_at DESC, created_at DESC, id ASC
            """,
            params,
        ).fetchall()
    return [_conversation_from_row(row) for row in rows]


def get_conversation(conversation_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM conversations WHERE id = ? AND test_run_id = ?",
            (conversation_id, test_run_id),
        ).fetchone()
    if row is None:
        raise NotFoundError("Conversation not found.")
    return _conversation_from_row(row)


def archive_conversation(conversation_id: str, *, test_run_id: str) -> dict[str, object]:
    now = utc_now()
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE conversations
            SET status = 'archived', archived_at = COALESCE(archived_at, ?), updated_at = ?
            WHERE id = ? AND test_run_id = ?
            """,
            (now, now, conversation_id, test_run_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError("Conversation not found.")
    return get_conversation(conversation_id, test_run_id=test_run_id)


def update_conversation(
    conversation_id: str,
    *,
    title: str | None,
    test_run_id: str,
) -> dict[str, object]:
    if title is None:
        return get_conversation(conversation_id, test_run_id=test_run_id)
    clean_title = title.strip()
    if not clean_title:
        raise ValidationError("Conversation title is required.", code="conversation_title_required")
    now = utc_now()
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE conversations
            SET title = ?, updated_at = ?
            WHERE id = ? AND test_run_id = ? AND archived_at IS NULL
            """,
            (clean_title, now, conversation_id, test_run_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError("Conversation not found.")
    return get_conversation(conversation_id, test_run_id=test_run_id)


def delete_conversation(conversation_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        conversation = connection.execute(
            "SELECT * FROM conversations WHERE id = ? AND test_run_id = ?",
            (conversation_id, test_run_id),
        ).fetchone()
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        storage_keys = _conversation_artifact_storage_keys(connection, conversation_id, test_run_id)
        cursor = connection.execute(
            "DELETE FROM conversations WHERE id = ? AND test_run_id = ?",
            (conversation_id, test_run_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError("Conversation not found.")

    deleted_files, delete_errors = _delete_artifact_files(storage_keys)
    payload = _conversation_from_row(conversation)
    payload["status"] = "deleted"
    payload["deleted"] = True
    payload["hard_deleted"] = True
    payload["artifact_files_deleted"] = deleted_files
    if delete_errors:
        payload["artifact_file_delete_errors"] = delete_errors
    return payload


def create_message(
    *,
    conversation_id: str,
    message_type: str,
    content: dict[str, object],
    mentions: list[dict[str, object]],
    references: list[dict[str, object]],
    reply_to_id: str | None,
    test_run_id: str,
) -> dict[str, object]:
    if not message_type:
        raise ValidationError("Message type is required.")
    if not isinstance(content, dict):
        raise ValidationError("Message content must be an object.")

    message_id = f"msg_{uuid.uuid4().hex}"
    now = utc_now()
    encoded_content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    encoded_mentions = json.dumps(mentions, ensure_ascii=False, separators=(",", ":"))
    encoded_references = json.dumps(references, ensure_ascii=False, separators=(",", ":"))
    with connect() as connection:
        conversation = connection.execute(
            "SELECT id FROM conversations WHERE id = ? AND test_run_id = ?",
            (conversation_id, test_run_id),
        ).fetchone()
        if conversation is None:
            raise NotFoundError("Conversation not found.")

        if reply_to_id:
            reply_to = connection.execute(
                """
                SELECT id
                FROM messages
                WHERE id = ? AND conversation_id = ? AND test_run_id = ?
                """,
                (reply_to_id, conversation_id, test_run_id),
            ).fetchone()
            if reply_to is None:
                raise ValidationError("reply_to_id must reference a message in the same conversation.")

        validate_artifact_references(
            conversation_id=conversation_id,
            references=references,
            test_run_id=test_run_id,
        )

        connection.execute(
            """
            INSERT INTO messages (
                id, conversation_id, sender_type, sender_id, message_type,
                content_json, mentions_json, references_json, reply_to_id,
                test_run_id, created_at
            )
            VALUES (?, ?, 'user', 'user', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                conversation_id,
                message_type,
                encoded_content,
                encoded_mentions,
                encoded_references,
                reply_to_id,
                test_run_id,
                now,
            ),
        )
        connection.execute(
            """
            UPDATE conversations
            SET updated_at = ?, last_active_at = ?
            WHERE id = ? AND test_run_id = ?
            """,
            (now, now, conversation_id, test_run_id),
        )
        record_event(
            connection,
            conversation_id=conversation_id,
            event_type="message.created",
            payload={
                "message_id": message_id,
                "sender_type": "user",
                "sender_id": "user",
                "message_type": message_type,
                "reply_to_id": reply_to_id,
                "mentions_count": len(mentions),
                "references_count": len(references),
            },
        )

    return get_message(message_id, test_run_id=test_run_id)


def create_error_message(
    *,
    conversation_id: str,
    sender_id: str,
    error_card: dict[str, object],
    reply_to_id: str | None,
    test_run_id: str,
) -> dict[str, object]:
    error_code = str(error_card.get("error_code") or "request_failed")
    message = str(error_card.get("message") or "Agent execution failed.")
    encoded_content = json.dumps(
        {
            "text": message,
            "error_card": error_card,
            "error_code": error_code,
            "recovery_hint": error_card.get("recovery_hint"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    message_id = f"msg_{uuid.uuid4().hex}"
    now = utc_now()
    with connect() as connection:
        conversation = connection.execute(
            "SELECT id FROM conversations WHERE id = ? AND test_run_id = ?",
            (conversation_id, test_run_id),
        ).fetchone()
        if conversation is None:
            raise NotFoundError("Conversation not found.")

        if reply_to_id:
            reply_to = connection.execute(
                """
                SELECT id
                FROM messages
                WHERE id = ? AND conversation_id = ? AND test_run_id = ?
                """,
                (reply_to_id, conversation_id, test_run_id),
            ).fetchone()
            if reply_to is None:
                raise ValidationError("reply_to_id must reference a message in the same conversation.")

        connection.execute(
            """
            INSERT INTO messages (
                id, conversation_id, sender_type, sender_id, message_type,
                content_json, mentions_json, references_json, reply_to_id,
                created_by_run_id, test_run_id, created_at
            )
            VALUES (?, ?, 'assistant', ?, 'error', ?, '[]', '[]', ?, NULL, ?, ?)
            """,
            (
                message_id,
                conversation_id,
                sender_id,
                encoded_content,
                reply_to_id,
                test_run_id,
                now,
            ),
        )
        connection.execute(
            """
            UPDATE conversations
            SET updated_at = ?, last_active_at = ?
            WHERE id = ? AND test_run_id = ?
            """,
            (now, now, conversation_id, test_run_id),
        )
        record_event(
            connection,
            conversation_id=conversation_id,
            event_type="message.created",
            payload={
                "message_id": message_id,
                "sender_type": "assistant",
                "sender_id": sender_id,
                "message_type": "error",
                "reply_to_id": reply_to_id,
                "error_code": error_code,
            },
        )

    return get_message(message_id, test_run_id=test_run_id)


def create_assistant_message(
    *,
    conversation_id: str,
    sender_id: str,
    content_text: str,
    created_by_run_id: str,
    reply_to_id: str | None,
    test_run_id: str,
    artifact_references: list[dict[str, object]] | None = None,
    structured_content: dict[str, object] | None = None,
) -> dict[str, object]:
    content = dict(structured_content or {"text": content_text, "final_content": content_text})
    if "text" not in content:
        content["text"] = content_text
    if "final_content" not in content:
        content["final_content"] = content_text
    content["run_id"] = created_by_run_id
    final_content = content.get("final_content")
    raw_content = content.get("raw_content")
    if not (
        isinstance(final_content, str)
        and final_content.strip()
        or isinstance(raw_content, str)
        and raw_content.strip()
    ):
        raise ValidationError("Assistant message content is required.")

    message_id = f"msg_{uuid.uuid4().hex}"
    now = utc_now()
    encoded_content = json.dumps(
        content,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    references = artifact_references or []
    encoded_references = json.dumps(references, ensure_ascii=False, separators=(",", ":"))
    with connect() as connection:
        conversation = connection.execute(
            "SELECT id FROM conversations WHERE id = ? AND test_run_id = ?",
            (conversation_id, test_run_id),
        ).fetchone()
        if conversation is None:
            raise NotFoundError("Conversation not found.")

        run = connection.execute(
            """
            SELECT id
            FROM agent_runs
            WHERE id = ? AND conversation_id = ? AND test_run_id = ?
            """,
            (created_by_run_id, conversation_id, test_run_id),
        ).fetchone()
        if run is None:
            raise ValidationError("created_by_run_id must reference an AgentRun in the same conversation.")

        if reply_to_id:
            reply_to = connection.execute(
                """
                SELECT id
                FROM messages
                WHERE id = ? AND conversation_id = ? AND test_run_id = ?
                """,
                (reply_to_id, conversation_id, test_run_id),
            ).fetchone()
            if reply_to is None:
                raise ValidationError("reply_to_id must reference a message in the same conversation.")

        validate_artifact_references(
            conversation_id=conversation_id,
            references=references,
            test_run_id=test_run_id,
        )

        connection.execute(
            """
            INSERT INTO messages (
                id, conversation_id, sender_type, sender_id, message_type,
                content_json, mentions_json, references_json, reply_to_id,
                created_by_run_id, test_run_id, created_at
            )
            VALUES (?, ?, 'assistant', ?, 'text', ?, '[]', ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                conversation_id,
                sender_id,
                encoded_content,
                encoded_references,
                reply_to_id,
                created_by_run_id,
                test_run_id,
                now,
            ),
        )
        connection.execute(
            """
            UPDATE conversations
            SET updated_at = ?, last_active_at = ?
            WHERE id = ? AND test_run_id = ?
            """,
            (now, now, conversation_id, test_run_id),
        )
        record_event(
            connection,
            conversation_id=conversation_id,
            event_type="message.created",
            payload={
                "message_id": message_id,
                "sender_type": "assistant",
                "sender_id": sender_id,
                "message_type": "text",
                "reply_to_id": reply_to_id,
                "created_by_run_id": created_by_run_id,
                "references_count": len(references),
            },
            run_id=created_by_run_id,
        )

    return get_message(message_id, test_run_id=test_run_id)


def create_orchestrator_clarification_message(
    *,
    conversation_id: str,
    content_text: str,
    reply_to_id: str,
    test_run_id: str,
) -> dict[str, object]:
    if not content_text.strip():
        raise ValidationError("Clarification message content is required.")

    message_id = f"msg_{uuid.uuid4().hex}"
    now = utc_now()
    encoded_content = json.dumps(
        {"text": content_text, "clarification_for_message_id": reply_to_id},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    with connect() as connection:
        conversation = connection.execute(
            "SELECT id FROM conversations WHERE id = ? AND test_run_id = ?",
            (conversation_id, test_run_id),
        ).fetchone()
        if conversation is None:
            raise NotFoundError("Conversation not found.")

        reply_to = connection.execute(
            """
            SELECT id
            FROM messages
            WHERE id = ? AND conversation_id = ? AND test_run_id = ?
            """,
            (reply_to_id, conversation_id, test_run_id),
        ).fetchone()
        if reply_to is None:
            raise ValidationError("reply_to_id must reference a message in the same conversation.")

        connection.execute(
            """
            INSERT INTO messages (
                id, conversation_id, sender_type, sender_id, message_type,
                content_json, mentions_json, references_json, reply_to_id,
                created_by_run_id, test_run_id, created_at
            )
            VALUES (?, ?, 'assistant', 'orchestrator', 'text', ?, '[]', '[]', ?, NULL, ?, ?)
            """,
            (
                message_id,
                conversation_id,
                encoded_content,
                reply_to_id,
                test_run_id,
                now,
            ),
        )
        connection.execute(
            """
            UPDATE conversations
            SET updated_at = ?, last_active_at = ?
            WHERE id = ? AND test_run_id = ?
            """,
            (now, now, conversation_id, test_run_id),
        )
        record_event(
            connection,
            conversation_id=conversation_id,
            event_type="message.created",
            payload={
                "message_id": message_id,
                "sender_type": "assistant",
                "sender_id": "orchestrator",
                "message_type": "text",
                "reply_to_id": reply_to_id,
                "clarification_for_message_id": reply_to_id,
            },
        )

    return get_message(message_id, test_run_id=test_run_id)


def list_messages(conversation_id: str, *, test_run_id: str) -> list[dict[str, object]]:
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
            FROM messages
            WHERE conversation_id = ? AND test_run_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_id, test_run_id),
        ).fetchall()
    return [_message_from_row(row) for row in rows]


def get_message(message_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM messages WHERE id = ? AND test_run_id = ?",
            (message_id, test_run_id),
        ).fetchone()
    if row is None:
        raise NotFoundError("Message not found.")
    return _message_from_row(row)


def list_members(conversation_id: str, *, test_run_id: str) -> list[dict[str, object]]:
    with connect() as connection:
        conversation = connection.execute(
            "SELECT id FROM conversations WHERE id = ? AND test_run_id = ?",
            (conversation_id, test_run_id),
        ).fetchone()
        if conversation is None:
            raise NotFoundError("Conversation not found.")

        rows = connection.execute(
            """
            SELECT
                cm.member_type,
                cm.member_id,
                cm.created_at,
                a.name AS agent_name,
                a.provider AS agent_provider,
                a.avatar AS agent_avatar,
                a.initials AS agent_initials,
                a.capability_tags_json AS agent_capability_tags_json,
                a.execution_enabled AS agent_execution_enabled,
                a.configured AS agent_configured,
                a.health_status AS agent_health_status
            FROM conversation_members cm
            LEFT JOIN agents a
                ON cm.member_type = 'agent' AND cm.member_id = a.id
            WHERE cm.conversation_id = ?
            ORDER BY
                CASE cm.member_type
                    WHEN 'user' THEN 0
                    WHEN 'orchestrator' THEN 1
                    ELSE 2
                END,
                cm.member_id ASC
            """,
            (conversation_id,),
        ).fetchall()

    return [_member_from_row(conversation_id, row) for row in rows]


def list_conversation_events(
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
    return list_events(
        conversation_id,
        test_run_id=test_run_id,
        after_sequence=after_sequence,
        task_id=task_id,
        run_id=run_id,
        artifact_id=artifact_id,
        deployment_id=deployment_id,
        limit=limit,
    )


def _conversation_artifact_storage_keys(connection, conversation_id: str, test_run_id: str) -> list[str]:
    if not _table_exists(connection, "artifacts") or not _table_exists(connection, "artifact_versions"):
        return []
    rows = connection.execute(
        """
        SELECT DISTINCT av.storage_key
        FROM artifact_versions av
        JOIN artifacts a ON a.id = av.artifact_id
        WHERE a.conversation_id = ? AND a.test_run_id = ? AND av.test_run_id = ?
        """,
        (conversation_id, test_run_id, test_run_id),
    ).fetchall()
    return [str(row["storage_key"]) for row in rows if row["storage_key"]]


def _delete_artifact_files(storage_keys: list[str]) -> tuple[int, list[str]]:
    root = artifact_store_root().resolve()
    deleted = 0
    errors: list[str] = []
    for storage_key in dict.fromkeys(storage_keys):
        if not storage_key or storage_key.startswith("/") or "\\" in storage_key:
            errors.append(f"invalid_storage_key:{storage_key}")
            continue
        path = (root / storage_key).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            errors.append(f"escaped_storage_key:{storage_key}")
            continue
        if not path.exists():
            continue
        if not path.is_file():
            errors.append(f"not_file:{storage_key}")
            continue
        try:
            path.unlink()
            deleted += 1
            _remove_empty_parents(path.parent, root)
        except OSError as exc:
            errors.append(f"{storage_key}:{exc}")
    return deleted, errors


def _remove_empty_parents(path: Path, root: Path) -> None:
    current = path.resolve()
    while current != root:
        try:
            current.relative_to(root)
        except ValueError:
            return
        with suppress(OSError):
            current.rmdir()
        if current.exists():
            return
        current = current.parent


def _table_exists(connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _insert_member(connection, conversation_id: str, member_type: str, member_id: str, created_at: str) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO conversation_members (
            conversation_id, member_type, member_id, created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (conversation_id, member_type, member_id, created_at),
    )


def _conversation_from_row(row: Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "title": row["title"],
        "mode": row["mode"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_active_at": row["last_active_at"],
        "archived_at": row["archived_at"],
    }


def _message_from_row(row: Row) -> dict[str, object]:
    references = json.loads(row["references_json"])
    message = {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "sender_type": row["sender_type"],
        "sender_id": row["sender_id"],
        "message_type": row["message_type"],
        "content": json.loads(row["content_json"]),
        "mentions": json.loads(row["mentions_json"]),
        "references": references,
        "reply_to_id": row["reply_to_id"],
        "created_by_run_id": row["created_by_run_id"],
        "created_at": row["created_at"],
    }
    cards = artifact_cards_for_references(references, test_run_id=row["test_run_id"])
    diff_cards = [card for card in cards if card.get("card_type") == "diff_card"]
    artifact_cards = [card for card in cards if card.get("card_type") != "diff_card"]
    if artifact_cards:
        message["artifact_cards"] = artifact_cards
        if len(artifact_cards) == 1:
            message["artifact_card"] = artifact_cards[0]
    if diff_cards:
        message["diff_cards"] = diff_cards
        if len(diff_cards) == 1:
            message["diff_card"] = diff_cards[0]
    return message


def _member_from_row(conversation_id: str, row: Row) -> dict[str, object]:
    member_type = row["member_type"]
    if member_type == "agent":
        return {
            "conversation_id": conversation_id,
            "member_type": "agent",
            "member_id": row["member_id"],
            "name": row["agent_name"],
            "provider": row["agent_provider"],
            "avatar": row["agent_avatar"],
            "initials": row["agent_initials"],
            "capability_tags": json.loads(row["agent_capability_tags_json"] or "[]"),
            "execution_enabled": bool(row["agent_execution_enabled"]),
            "configured": bool(row["agent_configured"]),
            "health_status": row["agent_health_status"],
            "created_at": row["created_at"],
        }
    if member_type == "orchestrator":
        return {
            "conversation_id": conversation_id,
            "member_type": "orchestrator",
            "member_id": "orchestrator",
            "name": "Orchestrator",
            "created_at": row["created_at"],
        }
    return {
        "conversation_id": conversation_id,
        "member_type": "user",
        "member_id": "user",
        "name": "User",
        "created_at": row["created_at"],
    }
