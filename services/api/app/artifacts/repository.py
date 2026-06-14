from __future__ import annotations

import json
import re
import uuid
from sqlite3 import Connection, Row

from services.api.app.artifacts.schema import (
    DEPLOYMENT_RELEASE_ARTIFACT_TYPE,
    DIFF_ARTIFACT_TYPES,
    PATCH_ARTIFACT_TYPES,
    artifact_to_response,
    artifact_version_to_response,
    validate_artifact_input,
)
from services.api.app.artifacts.office import render_office_artifact
from services.api.app.artifacts.store import read_content, storage_key_for, write_content
from services.api.app.execution.events import record_event
from services.api.app.permissions import audit_repository
from services.api.app.shared.database import connect
from services.api.app.shared.errors import NotFoundError, ValidationError
from services.api.app.shared.time import utc_now


_FILENAME_SANITIZE_RE = re.compile(r"[\x00-\x1f\x7f<>:\"/\\|?*]+")


def create_artifact(
    *,
    conversation_id: str,
    artifact_type: str,
    title: str,
    mime_type: str,
    content: bytes | str,
    task_id: str | None = None,
    created_by_run_id: str | None = None,
    status: str = "available",
    test_run_id: str,
    artifact_id: str | None = None,
    target_artifact_id: str | None = None,
    base_version_id: str | None = None,
    base_checksum: str | None = None,
    _allow_deployment_release: bool = False,
) -> dict[str, object]:
    artifact_input = validate_artifact_input(
        {
            "conversation_id": conversation_id,
            "task_id": task_id,
            "created_by_run_id": created_by_run_id,
            "type": artifact_type,
            "title": title,
            "status": status,
            "mime_type": mime_type,
        },
        allow_deployment_release=_allow_deployment_release,
    )
    artifact_id = artifact_id or f"art_{uuid.uuid4().hex}"
    version_id = f"artv_{uuid.uuid4().hex}"
    now = utc_now()
    storage_key = storage_key_for(
        test_run_id=test_run_id,
        conversation_id=str(artifact_input["conversation_id"]),
        artifact_id=artifact_id,
        version=1,
    )
    with connect() as connection:
        _ensure_artifact_tables(connection)
        _validate_sources(
            connection,
            conversation_id=str(artifact_input["conversation_id"]),
            task_id=artifact_input["task_id"] if isinstance(artifact_input["task_id"], str) else None,
            created_by_run_id=artifact_input["created_by_run_id"]
            if isinstance(artifact_input["created_by_run_id"], str)
            else None,
            test_run_id=test_run_id,
        )
        _validate_patch_metadata(
            connection,
            artifact_type=str(artifact_input["type"]),
            conversation_id=str(artifact_input["conversation_id"]),
            target_artifact_id=target_artifact_id,
            base_version_id=base_version_id,
            test_run_id=test_run_id,
        )
    checksum = write_content(storage_key, content)

    with connect() as connection:
        _ensure_artifact_tables(connection)
        connection.execute(
            """
            INSERT INTO artifacts (
                id, conversation_id, task_id, created_by_run_id, type, title,
                status, mime_type, storage_key, current_version_id,
                test_run_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                artifact_input["conversation_id"],
                artifact_input["task_id"],
                artifact_input["created_by_run_id"],
                artifact_input["type"],
                artifact_input["title"],
                artifact_input["status"],
                artifact_input["mime_type"],
                storage_key,
                version_id,
                test_run_id,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO artifact_versions (
                id, artifact_id, version, storage_key, checksum,
                parent_version_id, test_run_id, created_at
            )
            VALUES (?, ?, 1, ?, ?, NULL, ?, ?)
            """,
            (version_id, artifact_id, storage_key, checksum, test_run_id, now),
        )
        if str(artifact_input["type"]) in PATCH_ARTIFACT_TYPES:
            connection.execute(
                """
                INSERT INTO artifact_patches (
                    patch_artifact_id, target_artifact_id, base_version_id,
                    base_checksum, test_run_id
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (artifact_id, target_artifact_id, base_version_id, base_checksum, test_run_id),
            )
        record_event(
            connection,
            conversation_id=str(artifact_input["conversation_id"]),
            task_id=artifact_input["task_id"] if isinstance(artifact_input["task_id"], str) else None,
            run_id=artifact_input["created_by_run_id"]
            if isinstance(artifact_input["created_by_run_id"], str)
            else None,
            artifact_id=artifact_id,
            event_type="artifact.created",
            payload={
                "artifact_id": artifact_id,
                "type": artifact_input["type"],
                "title": artifact_input["title"],
                "status": artifact_input["status"],
                "mime_type": artifact_input["mime_type"],
                "current_version_id": version_id,
                "version": 1,
            },
            created_at=now,
        )
        record_event(
            connection,
            conversation_id=str(artifact_input["conversation_id"]),
            task_id=artifact_input["task_id"] if isinstance(artifact_input["task_id"], str) else None,
            run_id=artifact_input["created_by_run_id"]
            if isinstance(artifact_input["created_by_run_id"], str)
            else None,
            artifact_id=artifact_id,
            event_type="artifact.version_created",
            payload={
                "artifact_id": artifact_id,
                "version_id": version_id,
                "version": 1,
                "checksum": checksum,
                "parent_version_id": None,
            },
            created_at=now,
        )
    return get_artifact(artifact_id, test_run_id=test_run_id)


def create_deployment_release_artifact(
    *,
    conversation_id: str,
    title: str,
    content: str,
    status: str,
    test_run_id: str,
) -> dict[str, object]:
    return create_artifact(
        conversation_id=conversation_id,
        artifact_type=DEPLOYMENT_RELEASE_ARTIFACT_TYPE,
        title=title,
        mime_type="application/json",
        content=content,
        status=status,
        test_run_id=test_run_id,
        _allow_deployment_release=True,
    )


def create_artifact_from_agent_output(
    *,
    run: dict[str, object],
    content_text: str,
    expected_artifacts: list[dict[str, object]],
    test_run_id: str,
) -> dict[str, object] | None:
    spec = _first_supported_expected_artifact(expected_artifacts)
    if spec is None:
        return None

    title = _expected_string(spec, "title") or _title_from_output(content_text)
    artifact_type = _expected_string(spec, "type") or "document"
    mime_type = _expected_string(spec, "mime_type") or "text/markdown"
    title, mime_type, content = render_office_artifact(
        artifact_type=artifact_type,
        title=title,
        mime_type=mime_type,
        content_text=content_text,
    )
    task_id = _task_id_for_run(str(run["id"]), test_run_id=test_run_id)
    return create_artifact(
        conversation_id=str(run["conversation_id"]),
        artifact_type=artifact_type,
        title=title,
        mime_type=mime_type,
        content=content,
        task_id=task_id,
        created_by_run_id=str(run["id"]),
        test_run_id=test_run_id,
    )


def list_artifacts(
    *,
    test_run_id: str,
    conversation_id: str | None = None,
    artifact_type: str | None = None,
    created_by_run_id: str | None = None,
) -> list[dict[str, object]]:
    filters = ["a.test_run_id = ?"]
    params: list[object] = [test_run_id]
    if conversation_id:
        filters.append("a.conversation_id = ?")
        params.append(conversation_id)
    if artifact_type:
        filters.append("a.type = ?")
        params.append(artifact_type)
    if created_by_run_id:
        filters.append("a.created_by_run_id = ?")
        params.append(created_by_run_id)

    with connect() as connection:
        _ensure_artifact_tables(connection)
        rows = connection.execute(
            f"""
            SELECT
                a.*,
                av.version AS version,
                av.checksum AS checksum,
                ad.base_artifact_id AS diff_base_artifact_id,
                ad.base_version_id AS diff_base_version_id,
                ad.target_artifact_id AS diff_target_artifact_id,
                ad.target_version_id AS diff_target_version_id,
                ad.additions AS diff_additions,
                ad.deletions AS diff_deletions,
                ad.base_checksum AS diff_base_checksum,
                ad.target_checksum AS diff_target_checksum,
                ap.target_artifact_id AS patch_target_artifact_id,
                ap.base_version_id AS patch_base_version_id,
                ap.base_checksum AS patch_base_checksum
            FROM artifacts a
            LEFT JOIN artifact_versions av ON av.id = a.current_version_id
            LEFT JOIN artifact_diffs ad ON ad.diff_artifact_id = a.id
            LEFT JOIN artifact_patches ap ON ap.patch_artifact_id = a.id
            WHERE {" AND ".join(filters)}
            ORDER BY a.created_at ASC, a.id ASC
            """,
            params,
        ).fetchall()
    return [artifact_to_response(_artifact_from_row(row)) for row in rows]


def get_artifact(artifact_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        _ensure_artifact_tables(connection)
        row = connection.execute(
            """
            SELECT
                a.*,
                av.version AS version,
                av.checksum AS checksum,
                ad.base_artifact_id AS diff_base_artifact_id,
                ad.base_version_id AS diff_base_version_id,
                ad.target_artifact_id AS diff_target_artifact_id,
                ad.target_version_id AS diff_target_version_id,
                ad.additions AS diff_additions,
                ad.deletions AS diff_deletions,
                ad.base_checksum AS diff_base_checksum,
                ad.target_checksum AS diff_target_checksum,
                ap.target_artifact_id AS patch_target_artifact_id,
                ap.base_version_id AS patch_base_version_id,
                ap.base_checksum AS patch_base_checksum
            FROM artifacts a
            LEFT JOIN artifact_versions av ON av.id = a.current_version_id
            LEFT JOIN artifact_diffs ad ON ad.diff_artifact_id = a.id
            LEFT JOIN artifact_patches ap ON ap.patch_artifact_id = a.id
            WHERE a.id = ? AND a.test_run_id = ?
            """,
            (artifact_id, test_run_id),
        ).fetchone()
    if row is None:
        raise NotFoundError("Artifact not found.")
    return artifact_to_response(_artifact_from_row(row))


def list_artifact_versions(artifact_id: str, *, test_run_id: str) -> list[dict[str, object]]:
    with connect() as connection:
        _ensure_artifact_tables(connection)
        _artifact_row(connection, artifact_id, test_run_id=test_run_id)
        rows = connection.execute(
            """
            SELECT *
            FROM artifact_versions
            WHERE artifact_id = ? AND test_run_id = ?
            ORDER BY version ASC
            """,
            (artifact_id, test_run_id),
        ).fetchall()
    return [artifact_version_to_response(_version_from_row(row)) for row in rows]


def read_artifact_content(
    artifact_id: str,
    *,
    test_run_id: str,
    version: int | None = None,
) -> dict[str, object]:
    artifact, version_payload = _resolve_download_artifact_version(
        artifact_id,
        test_run_id=test_run_id,
        version=version,
    )
    raw = read_content(
        str(version_payload["storage_key"]),
        expected_checksum=str(version_payload["checksum"]),
    )
    content_text = raw.decode("utf-8", errors="replace")
    return {
        "artifact_id": artifact_id,
        "version_id": version_payload["id"],
        "version": version_payload["version"],
        "mime_type": artifact["mime_type"],
        "checksum": version_payload["checksum"],
        "content": content_text,
        "encoding": "utf-8",
    }


def read_artifact_download(
    artifact_id: str,
    *,
    test_run_id: str,
    version: int | None = None,
) -> dict[str, object]:
    artifact, version_payload = _resolve_download_artifact_version(
        artifact_id,
        test_run_id=test_run_id,
        version=version,
    )
    raw = read_content(
        str(version_payload["storage_key"]),
        expected_checksum=str(version_payload["checksum"]),
    )
    return {
        "artifact_id": artifact_id,
        "version_id": version_payload["id"],
        "version": version_payload["version"],
        "mime_type": artifact["mime_type"],
        "checksum": version_payload["checksum"],
        "filename": _download_filename(str(artifact["title"])),
        "content": raw,
        "content_length": len(raw),
    }


def append_artifact_version(
    artifact_id: str,
    *,
    content: bytes | str,
    parent_version_id: str,
    test_run_id: str,
) -> dict[str, object]:
    version_id = f"artv_{uuid.uuid4().hex}"
    now = utc_now()
    with connect() as connection:
        _ensure_artifact_tables(connection)
        artifact = _artifact_row(connection, artifact_id, test_run_id=test_run_id)
        parent = connection.execute(
            """
            SELECT *
            FROM artifact_versions
            WHERE id = ? AND artifact_id = ? AND test_run_id = ?
            """,
            (parent_version_id, artifact_id, test_run_id),
        ).fetchone()
        if parent is None:
            raise ValidationError("parent_version_id must reference the target artifact.", code="artifact_parent_invalid")
        current_version = connection.execute(
            """
            SELECT COALESCE(MAX(version), 0) AS version
            FROM artifact_versions
            WHERE artifact_id = ? AND test_run_id = ?
            """,
            (artifact_id, test_run_id),
        ).fetchone()
        next_version = int(current_version["version"]) + 1
        conversation_id = str(artifact["conversation_id"])

    storage_key = storage_key_for(
        test_run_id=test_run_id,
        conversation_id=conversation_id,
        artifact_id=artifact_id,
        version=next_version,
    )
    checksum = write_content(storage_key, content)

    with connect() as connection:
        _ensure_artifact_tables(connection)
        connection.execute(
            """
            INSERT INTO artifact_versions (
                id, artifact_id, version, storage_key, checksum,
                parent_version_id, test_run_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (version_id, artifact_id, next_version, storage_key, checksum, parent_version_id, test_run_id, now),
        )
        connection.execute(
            """
            UPDATE artifacts
            SET storage_key = ?, current_version_id = ?
            WHERE id = ? AND test_run_id = ?
            """,
            (storage_key, version_id, artifact_id, test_run_id),
        )
        record_event(
            connection,
            conversation_id=conversation_id,
            artifact_id=artifact_id,
            event_type="artifact.version_created",
            payload={
                "artifact_id": artifact_id,
                "version_id": version_id,
                "version": next_version,
                "checksum": checksum,
                "parent_version_id": parent_version_id,
            },
            created_at=now,
        )
    return get_artifact_version_record(artifact_id, version_id, test_run_id=test_run_id)


def append_artifact_version_with_patch_application(
    artifact_id: str,
    *,
    content: bytes | str,
    parent_version_id: str,
    patch_artifact_id: str | None,
    diff_artifact_id: str | None,
    target_artifact_id: str,
    base_version_id: str,
    test_run_id: str,
) -> dict[str, object]:
    if patch_artifact_id is None and diff_artifact_id is None:
        raise ValidationError("PatchApplication must reference a patch or diff artifact.", code="patch_application_invalid")

    version_id = f"artv_{uuid.uuid4().hex}"
    application_id = f"patchapp_{uuid.uuid4().hex}"
    now = utc_now()
    with connect() as connection:
        _ensure_artifact_tables(connection)
        audit_repository.ensure_audit_log_table(connection)
        connection.execute("BEGIN IMMEDIATE")
        artifact = _artifact_row(connection, artifact_id, test_run_id=test_run_id)
        if str(artifact["current_version_id"]) != parent_version_id:
            raise ValidationError(
                "Patch base version is no longer current.",
                code="artifact_apply_stale_base",
            )
        parent = connection.execute(
            """
            SELECT *
            FROM artifact_versions
            WHERE id = ? AND artifact_id = ? AND test_run_id = ?
            """,
            (parent_version_id, artifact_id, test_run_id),
        ).fetchone()
        if parent is None:
            raise ValidationError("parent_version_id must reference the target artifact.", code="artifact_parent_invalid")
        current_version = connection.execute(
            """
            SELECT COALESCE(MAX(version), 0) AS version
            FROM artifact_versions
            WHERE artifact_id = ? AND test_run_id = ?
            """,
            (artifact_id, test_run_id),
        ).fetchone()
        next_version = int(current_version["version"]) + 1
        storage_key = storage_key_for(
            test_run_id=test_run_id,
            conversation_id=str(artifact["conversation_id"]),
            artifact_id=artifact_id,
            version=next_version,
        )
        checksum = write_content(storage_key, content)
        connection.execute(
            """
            INSERT INTO artifact_versions (
                id, artifact_id, version, storage_key, checksum,
                parent_version_id, test_run_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (version_id, artifact_id, next_version, storage_key, checksum, parent_version_id, test_run_id, now),
        )
        connection.execute(
            """
            UPDATE artifacts
            SET storage_key = ?, current_version_id = ?
            WHERE id = ? AND test_run_id = ?
            """,
            (storage_key, version_id, artifact_id, test_run_id),
        )
        connection.execute(
            """
            INSERT INTO patch_applications (
                id, patch_artifact_id, diff_artifact_id, target_artifact_id,
                base_version_id, result_version_id, status, error_code,
                test_run_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'applied', NULL, ?, ?)
            """,
            (
                application_id,
                patch_artifact_id,
                diff_artifact_id,
                target_artifact_id,
                base_version_id,
                version_id,
                test_run_id,
                now,
            ),
        )
        audit_log = audit_repository.record_audit_log(
            connection,
            actor_type="system",
            actor_id="agenthub",
            action_type="patch_application.applied",
            target_type="patch_application",
            target_id=application_id,
            payload={
                "patch_artifact_id": patch_artifact_id,
                "diff_artifact_id": diff_artifact_id,
                "target_artifact_id": target_artifact_id,
                "base_version_id": base_version_id,
                "result_version_id": version_id,
                "status": "applied",
                "error_code": None,
            },
            test_run_id=test_run_id,
        )
        record_event(
            connection,
            conversation_id=str(artifact["conversation_id"]),
            artifact_id=artifact_id,
            event_type="artifact.version_created",
            payload={
                "artifact_id": artifact_id,
                "version_id": version_id,
                "version": next_version,
                "checksum": checksum,
                "parent_version_id": parent_version_id,
                "patch_application_id": application_id,
            },
            created_at=now,
        )
        record_event(
            connection,
            conversation_id=str(artifact["conversation_id"]),
            artifact_id=target_artifact_id,
            event_type="patch_application.applied",
            payload={
                "patch_application_id": application_id,
                "patch_artifact_id": patch_artifact_id,
                "diff_artifact_id": diff_artifact_id,
                "target_artifact_id": target_artifact_id,
                "base_version_id": base_version_id,
                "result_version_id": version_id,
                "status": "applied",
                "error_code": None,
            },
            created_at=now,
        )
    application = {
        "id": application_id,
        "patch_artifact_id": patch_artifact_id,
        "diff_artifact_id": diff_artifact_id,
        "target_artifact_id": target_artifact_id,
        "base_version_id": base_version_id,
        "result_version_id": version_id,
        "status": "applied",
        "error_code": None,
        "created_at": now,
        "audit_log_id": audit_log["id"],
        "new_version_id": version_id,
    }
    return application


def _resolve_download_artifact_version(
    artifact_id: str,
    *,
    test_run_id: str,
    version: int | None,
) -> tuple[dict[str, object], dict[str, object]]:
    with connect() as connection:
        _ensure_artifact_tables(connection)
        artifact = _artifact_row(connection, artifact_id, test_run_id=test_run_id)
        if version is None:
            version_row = connection.execute(
                "SELECT * FROM artifact_versions WHERE id = ? AND test_run_id = ?",
                (artifact["current_version_id"], test_run_id),
            ).fetchone()
        else:
            version_row = connection.execute(
                """
                SELECT *
                FROM artifact_versions
                WHERE artifact_id = ? AND version = ? AND test_run_id = ?
                """,
                (artifact_id, version, test_run_id),
            ).fetchone()
    if version_row is None:
        raise NotFoundError("ArtifactVersion not found.")
    return {
        "id": artifact["id"],
        "title": artifact["title"],
        "mime_type": artifact["mime_type"],
        "current_version_id": artifact["current_version_id"],
    }, _version_from_row(version_row)


def _download_filename(title: str) -> str:
    candidate = title.strip().replace("\\", "/").rsplit("/", 1)[-1]
    candidate = _FILENAME_SANITIZE_RE.sub("_", candidate).strip(" .")
    return candidate or "artifact.bin"


def get_current_artifact_version_record(artifact_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        _ensure_artifact_tables(connection)
        row = connection.execute(
            """
            SELECT current_version_id
            FROM artifacts
            WHERE id = ? AND test_run_id = ?
            """,
            (artifact_id, test_run_id),
        ).fetchone()
    if row is None:
        raise NotFoundError("Artifact not found.")
    return get_artifact_version_record(artifact_id, str(row["current_version_id"]), test_run_id=test_run_id)


def get_artifact_version_record(
    artifact_id: str,
    version_id: str,
    *,
    test_run_id: str,
) -> dict[str, object]:
    with connect() as connection:
        _ensure_artifact_tables(connection)
        row = connection.execute(
            """
            SELECT
                a.id AS artifact_id,
                a.conversation_id AS conversation_id,
                a.title AS artifact_title,
                a.type AS artifact_type,
                a.mime_type AS artifact_mime_type,
                av.id AS version_id,
                av.version AS version,
                av.storage_key AS storage_key,
                av.checksum AS checksum,
                av.parent_version_id AS parent_version_id,
                av.created_at AS version_created_at
            FROM artifacts a
            JOIN artifact_versions av ON av.artifact_id = a.id
            WHERE a.id = ? AND av.id = ? AND a.test_run_id = ? AND av.test_run_id = ?
            """,
            (artifact_id, version_id, test_run_id, test_run_id),
        ).fetchone()
    if row is None:
        raise NotFoundError("ArtifactVersion not found.")
    return {
        "artifact_id": row["artifact_id"],
        "conversation_id": row["conversation_id"],
        "artifact_title": row["artifact_title"],
        "artifact_type": row["artifact_type"],
        "artifact_mime_type": row["artifact_mime_type"],
        "version_id": row["version_id"],
        "version": row["version"],
        "storage_key": row["storage_key"],
        "checksum": row["checksum"],
        "parent_version_id": row["parent_version_id"],
        "created_at": row["version_created_at"],
    }


def create_artifact_diff_record(
    *,
    diff_artifact_id: str,
    base_artifact_id: str,
    base_version_id: str,
    target_artifact_id: str,
    target_version_id: str,
    files: list[dict[str, object]],
    hunks: list[dict[str, object]],
    additions: int,
    deletions: int,
    checksum: str,
    base_checksum: str,
    target_checksum: str,
    test_run_id: str,
) -> None:
    with connect() as connection:
        _ensure_artifact_tables(connection)
        diff_artifact = _artifact_row(connection, diff_artifact_id, test_run_id=test_run_id)
        connection.execute(
            """
            INSERT INTO artifact_diffs (
                diff_artifact_id, base_artifact_id, base_version_id,
                target_artifact_id, target_version_id, files_json, hunks_json,
                additions, deletions, checksum, base_checksum, target_checksum,
                test_run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                diff_artifact_id,
                base_artifact_id,
                base_version_id,
                target_artifact_id,
                target_version_id,
                json.dumps(files, ensure_ascii=False, separators=(",", ":")),
                json.dumps(hunks, ensure_ascii=False, separators=(",", ":")),
                additions,
                deletions,
                checksum,
                base_checksum,
                target_checksum,
                test_run_id,
            ),
        )
        record_event(
            connection,
            conversation_id=str(diff_artifact["conversation_id"]),
            artifact_id=diff_artifact_id,
            event_type="diff.created",
            payload={
                "diff_artifact_id": diff_artifact_id,
                "base_artifact_id": base_artifact_id,
                "base_version_id": base_version_id,
                "target_artifact_id": target_artifact_id,
                "target_version_id": target_version_id,
                "additions": additions,
                "deletions": deletions,
                "checksum": checksum,
            },
        )


def get_diff_artifact(diff_artifact_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        _ensure_artifact_tables(connection)
        row = connection.execute(
            """
            SELECT
                a.id AS artifact_id,
                a.type AS artifact_type,
                a.title AS title,
                a.mime_type AS mime_type,
                a.status AS status,
                a.conversation_id AS conversation_id,
                av.id AS version_id,
                av.version AS version,
                av.checksum AS artifact_checksum,
                ad.*
            FROM artifacts a
            JOIN artifact_versions av ON av.id = a.current_version_id
            JOIN artifact_diffs ad ON ad.diff_artifact_id = a.id
            WHERE a.id = ? AND a.test_run_id = ? AND ad.test_run_id = ?
            """,
            (diff_artifact_id, test_run_id, test_run_id),
        ).fetchone()
    if row is None:
        raise ValidationError("Diff artifact not found.", code="artifact_diff_not_found")
    return {
        "diff_artifact_id": row["diff_artifact_id"],
        "artifact_id": row["artifact_id"],
        "conversation_id": row["conversation_id"],
        "type": row["artifact_type"],
        "title": row["title"],
        "mime_type": row["mime_type"],
        "status": row["status"],
        "version_id": row["version_id"],
        "version": row["version"],
        "base_artifact_id": row["base_artifact_id"],
        "base_version_id": row["base_version_id"],
        "target_artifact_id": row["target_artifact_id"],
        "target_version_id": row["target_version_id"],
        "files": json.loads(row["files_json"]),
        "hunks": json.loads(row["hunks_json"]),
        "additions": row["additions"],
        "deletions": row["deletions"],
        "checksum": row["artifact_checksum"],
        "base_checksum": row["base_checksum"],
        "target_checksum": row["target_checksum"],
    }


def validate_artifact_references(
    *,
    conversation_id: str,
    references: list[dict[str, object]],
    test_run_id: str,
) -> None:
    artifact_ids = [
        str(reference["artifact_id"])
        for reference in references
        if _is_artifact_reference(reference) and isinstance(reference.get("artifact_id"), str)
    ]
    if not artifact_ids:
        return
    placeholders = ",".join("?" for _ in artifact_ids)
    with connect() as connection:
        _ensure_artifact_tables(connection)
        rows = connection.execute(
            f"""
            SELECT id
            FROM artifacts
            WHERE conversation_id = ? AND test_run_id = ? AND id IN ({placeholders})
            """,
            [conversation_id, test_run_id, *artifact_ids],
        ).fetchall()
    found = {row["id"] for row in rows}
    missing = [artifact_id for artifact_id in artifact_ids if artifact_id not in found]
    if missing:
        raise ValidationError("Artifact references must belong to the same conversation.", code="artifact_reference_invalid")


def artifact_cards_for_references(
    references: list[dict[str, object]],
    *,
    test_run_id: str,
) -> list[dict[str, object]]:
    artifact_ids = [
        str(reference["artifact_id"])
        for reference in references
        if _is_artifact_reference(reference) and isinstance(reference.get("artifact_id"), str)
    ]
    if not artifact_ids:
        return []
    placeholders = ",".join("?" for _ in artifact_ids)
    with connect() as connection:
        _ensure_artifact_tables(connection)
        rows = connection.execute(
            f"""
            SELECT
                a.*,
                av.version AS version,
                av.checksum AS checksum,
                ad.base_artifact_id AS diff_base_artifact_id,
                ad.base_version_id AS diff_base_version_id,
                ad.target_artifact_id AS diff_target_artifact_id,
                ad.target_version_id AS diff_target_version_id,
                ad.additions AS diff_additions,
                ad.deletions AS diff_deletions,
                ad.base_checksum AS diff_base_checksum,
                ad.target_checksum AS diff_target_checksum,
                ap.target_artifact_id AS patch_target_artifact_id,
                ap.base_version_id AS patch_base_version_id,
                ap.base_checksum AS patch_base_checksum
            FROM artifacts a
            LEFT JOIN artifact_versions av ON av.id = a.current_version_id
            LEFT JOIN artifact_diffs ad ON ad.diff_artifact_id = a.id
            LEFT JOIN artifact_patches ap ON ap.patch_artifact_id = a.id
            WHERE a.test_run_id = ? AND a.id IN ({placeholders})
            """,
            [test_run_id, *artifact_ids],
        ).fetchall()
    by_id = {row["id"]: _artifact_card_from_row(row) for row in rows}
    return [by_id[artifact_id] for artifact_id in artifact_ids if artifact_id in by_id]


def _ensure_artifact_tables(connection: Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            task_id TEXT,
            created_by_run_id TEXT,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            storage_key TEXT NOT NULL,
            current_version_id TEXT,
            test_run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS artifact_versions (
            id TEXT PRIMARY KEY,
            artifact_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            storage_key TEXT NOT NULL,
            checksum TEXT NOT NULL,
            parent_version_id TEXT,
            test_run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (artifact_id, version),
            FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_version_id) REFERENCES artifact_versions(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS artifact_diffs (
            diff_artifact_id TEXT PRIMARY KEY,
            base_artifact_id TEXT NOT NULL,
            base_version_id TEXT NOT NULL,
            target_artifact_id TEXT NOT NULL,
            target_version_id TEXT NOT NULL,
            files_json TEXT NOT NULL,
            hunks_json TEXT NOT NULL,
            additions INTEGER NOT NULL,
            deletions INTEGER NOT NULL,
            checksum TEXT NOT NULL,
            base_checksum TEXT NOT NULL,
            target_checksum TEXT NOT NULL,
            test_run_id TEXT NOT NULL,
            FOREIGN KEY (diff_artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
            FOREIGN KEY (base_artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
            FOREIGN KEY (base_version_id) REFERENCES artifact_versions(id) ON DELETE CASCADE,
            FOREIGN KEY (target_artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
            FOREIGN KEY (target_version_id) REFERENCES artifact_versions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS artifact_patches (
            patch_artifact_id TEXT PRIMARY KEY,
            target_artifact_id TEXT,
            base_version_id TEXT,
            base_checksum TEXT,
            test_run_id TEXT NOT NULL,
            FOREIGN KEY (patch_artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
            FOREIGN KEY (target_artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
            FOREIGN KEY (base_version_id) REFERENCES artifact_versions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS review_requests (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            action_type TEXT NOT NULL CHECK (action_type = 'apply_patch'),
            status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
            payload_json TEXT NOT NULL,
            test_run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS review_decisions (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
            decided_by TEXT NOT NULL,
            comment TEXT,
            test_run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (request_id) REFERENCES review_requests(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS patch_applications (
            id TEXT PRIMARY KEY,
            patch_artifact_id TEXT,
            diff_artifact_id TEXT,
            target_artifact_id TEXT NOT NULL,
            base_version_id TEXT NOT NULL,
            result_version_id TEXT,
            status TEXT NOT NULL CHECK (
                status IN ('review_required', 'applied', 'rejected', 'failed', 'conflict')
            ),
            error_code TEXT,
            test_run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            CHECK (patch_artifact_id IS NOT NULL OR diff_artifact_id IS NOT NULL),
            FOREIGN KEY (patch_artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
            FOREIGN KEY (diff_artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
            FOREIGN KEY (target_artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
            FOREIGN KEY (base_version_id) REFERENCES artifact_versions(id) ON DELETE CASCADE,
            FOREIGN KEY (result_version_id) REFERENCES artifact_versions(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_artifacts_conversation_created
            ON artifacts(test_run_id, conversation_id, created_at ASC);
        CREATE INDEX IF NOT EXISTS idx_artifacts_created_by_run
            ON artifacts(created_by_run_id);
        CREATE INDEX IF NOT EXISTS idx_artifact_versions_artifact
            ON artifact_versions(artifact_id, version ASC);
        CREATE INDEX IF NOT EXISTS idx_artifact_diffs_base
            ON artifact_diffs(test_run_id, base_artifact_id, base_version_id);
        CREATE INDEX IF NOT EXISTS idx_artifact_diffs_target
            ON artifact_diffs(test_run_id, target_artifact_id, target_version_id);
        CREATE INDEX IF NOT EXISTS idx_artifact_patches_target
            ON artifact_patches(test_run_id, target_artifact_id, base_version_id);
        CREATE INDEX IF NOT EXISTS idx_review_requests_artifact
            ON review_requests(test_run_id, artifact_id, action_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_patch_applications_artifact
            ON patch_applications(test_run_id, target_artifact_id, created_at DESC);
        """
    )
    _ensure_artifacts_agent_run_fk(connection)
    audit_repository.ensure_audit_log_table(connection)


def _ensure_artifacts_agent_run_fk(connection: Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'artifacts'"
    ).fetchone()
    if row is None or row[0] is None or "agent_runs_legacy_fk" not in str(row[0]):
        return
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("PRAGMA legacy_alter_table = ON")
    connection.executescript(
        """
        DROP INDEX IF EXISTS idx_artifacts_conversation_created;
        DROP INDEX IF EXISTS idx_artifacts_created_by_run;
        ALTER TABLE artifacts RENAME TO artifacts_legacy_fk;

        CREATE TABLE artifacts (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            task_id TEXT,
            created_by_run_id TEXT,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            storage_key TEXT NOT NULL,
            current_version_id TEXT,
            test_run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
        );

        INSERT INTO artifacts (
            id, conversation_id, task_id, created_by_run_id, type, title,
            status, mime_type, storage_key, current_version_id,
            test_run_id, created_at
        )
        SELECT
            id, conversation_id, task_id, created_by_run_id, type, title,
            status, mime_type, storage_key, current_version_id,
            test_run_id, created_at
        FROM artifacts_legacy_fk;

        DROP TABLE artifacts_legacy_fk;

        CREATE INDEX IF NOT EXISTS idx_artifacts_conversation_created
            ON artifacts(test_run_id, conversation_id, created_at ASC);
        CREATE INDEX IF NOT EXISTS idx_artifacts_created_by_run
            ON artifacts(created_by_run_id);
        """
    )
    connection.execute("PRAGMA legacy_alter_table = OFF")
    connection.execute("PRAGMA foreign_keys = ON")


def _validate_sources(
    connection: Connection,
    *,
    conversation_id: str,
    task_id: str | None,
    created_by_run_id: str | None,
    test_run_id: str,
) -> None:
    conversation = connection.execute(
        "SELECT id FROM conversations WHERE id = ? AND test_run_id = ?",
        (conversation_id, test_run_id),
    ).fetchone()
    if conversation is None:
        raise NotFoundError("Conversation not found.")

    if task_id is not None:
        task = connection.execute(
            "SELECT id FROM tasks WHERE id = ? AND conversation_id = ? AND test_run_id = ?",
            (task_id, conversation_id, test_run_id),
        ).fetchone()
        if task is None:
            raise ValidationError("task_id must reference a task in the same conversation.", code="artifact_source_invalid")

    if created_by_run_id is not None:
        run = connection.execute(
            "SELECT id FROM agent_runs WHERE id = ? AND conversation_id = ? AND test_run_id = ?",
            (created_by_run_id, conversation_id, test_run_id),
        ).fetchone()
        if run is None:
            raise ValidationError(
                "created_by_run_id must reference an AgentRun in the same conversation.",
                code="artifact_source_invalid",
            )


def _validate_patch_metadata(
    connection: Connection,
    *,
    artifact_type: str,
    conversation_id: str,
    target_artifact_id: str | None,
    base_version_id: str | None,
    test_run_id: str,
) -> None:
    if artifact_type not in PATCH_ARTIFACT_TYPES:
        if target_artifact_id is not None or base_version_id is not None:
            raise ValidationError(
                "target_artifact_id and base_version_id are only supported for patch artifacts.",
                code="artifact_patch_metadata_invalid",
            )
        return

    if target_artifact_id is None and base_version_id is None:
        return
    if target_artifact_id is None or base_version_id is None:
        raise ValidationError(
            "Patch artifacts must provide target_artifact_id and base_version_id together.",
            code="artifact_patch_metadata_invalid",
        )
    row = connection.execute(
        """
        SELECT a.conversation_id
        FROM artifacts a
        JOIN artifact_versions av ON av.artifact_id = a.id
        WHERE a.id = ? AND av.id = ? AND a.test_run_id = ? AND av.test_run_id = ?
        """,
        (target_artifact_id, base_version_id, test_run_id, test_run_id),
    ).fetchone()
    if row is None:
        raise ValidationError(
            "Patch target_artifact_id/base_version_id must reference an existing artifact version.",
            code="artifact_patch_metadata_invalid",
        )
    if row["conversation_id"] != conversation_id:
        raise ValidationError(
            "Patch artifact target must belong to the same conversation.",
            code="artifact_patch_metadata_invalid",
        )


def _artifact_row(connection: Connection, artifact_id: str, *, test_run_id: str) -> Row:
    row = connection.execute(
        "SELECT * FROM artifacts WHERE id = ? AND test_run_id = ?",
        (artifact_id, test_run_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("Artifact not found.")
    return row


def _task_id_for_run(run_id: str, *, test_run_id: str) -> str | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT t.id
            FROM agent_runs ar
            JOIN plan_steps ps ON ps.id = ar.plan_step_id
            JOIN plans p ON p.id = ps.plan_id
            JOIN tasks t ON t.id = p.task_id
            WHERE ar.id = ? AND ar.test_run_id = ?
            """,
            (run_id, test_run_id),
        ).fetchone()
    return str(row["id"]) if row is not None else None


def _artifact_from_row(row: Row) -> dict[str, object]:
    artifact = {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "task_id": row["task_id"],
        "created_by_run_id": row["created_by_run_id"],
        "type": row["type"],
        "title": row["title"],
        "status": row["status"],
        "mime_type": row["mime_type"],
        "storage_key": row["storage_key"],
        "current_version_id": row["current_version_id"],
        "version": row["version"],
        "checksum": row["checksum"],
        "created_at": row["created_at"],
    }
    if _row_value(row, "diff_base_artifact_id") is not None:
        artifact.update(
            {
                "diff_artifact_id": row["id"],
                "base_artifact_id": row["diff_base_artifact_id"],
                "base_version_id": row["diff_base_version_id"],
                "target_artifact_id": row["diff_target_artifact_id"],
                "target_version_id": row["diff_target_version_id"],
                "additions": row["diff_additions"],
                "deletions": row["diff_deletions"],
                "base_checksum": row["diff_base_checksum"],
                "target_checksum": row["diff_target_checksum"],
            }
        )
    if _row_value(row, "patch_target_artifact_id") is not None:
        artifact.update(
            {
                "patch_artifact_id": row["id"],
                "target_artifact_id": row["patch_target_artifact_id"],
                "base_version_id": row["patch_base_version_id"],
                "base_checksum": row["patch_base_checksum"],
            }
        )
    return artifact


def _version_from_row(row: Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "artifact_id": row["artifact_id"],
        "version": row["version"],
        "storage_key": row["storage_key"],
        "checksum": row["checksum"],
        "parent_version_id": row["parent_version_id"],
        "created_at": row["created_at"],
    }


def _artifact_card_from_row(row: Row) -> dict[str, object]:
    if row["type"] in DIFF_ARTIFACT_TYPES:
        return {
            "card_type": "diff_card",
            "diff_artifact_id": row["id"],
            "artifact_id": row["id"],
            "title": row["title"],
            "type": row["type"],
            "status": row["status"],
            "mime_type": row["mime_type"],
            "version": row["version"],
            "checksum": row["checksum"],
            "base_artifact_id": _row_value(row, "diff_base_artifact_id"),
            "base_version_id": _row_value(row, "diff_base_version_id"),
            "target_artifact_id": _row_value(row, "diff_target_artifact_id"),
            "target_version_id": _row_value(row, "diff_target_version_id"),
            "additions": _row_value(row, "diff_additions"),
            "deletions": _row_value(row, "diff_deletions"),
        }
    if row["type"] in PATCH_ARTIFACT_TYPES:
        return {
            "card_type": "patch_card",
            "patch_artifact_id": row["id"],
            "artifact_id": row["id"],
            "title": row["title"],
            "type": row["type"],
            "status": row["status"],
            "mime_type": row["mime_type"],
            "version": row["version"],
            "checksum": row["checksum"],
            "target_artifact_id": _row_value(row, "patch_target_artifact_id"),
            "base_version_id": _row_value(row, "patch_base_version_id"),
        }
    return {
        "card_type": "artifact_card",
        "artifact_id": row["id"],
        "title": row["title"],
        "type": row["type"],
        "status": row["status"],
        "mime_type": row["mime_type"],
        "version": row["version"],
        "checksum": row["checksum"],
    }


def _is_artifact_reference(reference: dict[str, object]) -> bool:
    return reference.get("type") in {"artifact", "diff_artifact", "diff"}


def _row_value(row: Row, key: str) -> object | None:
    return row[key] if key in row.keys() else None


def _first_supported_expected_artifact(expected_artifacts: list[dict[str, object]]) -> dict[str, object] | None:
    for item in expected_artifacts:
        try:
            validate_artifact_input(
                {
                    "conversation_id": "placeholder",
                    "type": _expected_string(item, "type") or "document",
                    "title": _expected_string(item, "title") or "Artifact",
                    "mime_type": _expected_string(item, "mime_type") or "text/markdown",
                }
            )
        except ValidationError:
            continue
        return item
    return None


def _expected_string(raw: dict[str, object], key: str) -> str | None:
    value = raw.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _title_from_output(content_text: str) -> str:
    for line in content_text.splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean[:120]
    return "Agent Output Artifact"
