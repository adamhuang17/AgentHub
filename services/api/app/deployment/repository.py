from __future__ import annotations

import uuid
from sqlite3 import Connection, Row

from services.api.app.deployment.schema import (
    DEPLOYMENT_RELEASE_STATUSES,
    deployment_release_to_response,
)
from services.api.app.execution.events import record_event
from services.api.app.shared.database import connect
from services.api.app.shared.errors import NotFoundError, ValidationError
from services.api.app.shared.time import utc_now


def create_deployment_release(
    *,
    artifact_id: str,
    artifact_version_id: str,
    provider: str,
    test_run_id: str,
    status: str = "created",
) -> dict[str, object]:
    if status not in DEPLOYMENT_RELEASE_STATUSES:
        raise ValidationError("Unsupported deployment release status.", code="deployment_release_invalid")
    release_id = f"depl_{uuid.uuid4().hex}"
    now = utc_now()
    with connect() as connection:
        ensure_deployment_tables(connection)
        artifact_version = _artifact_version_row(connection, artifact_id, artifact_version_id, test_run_id=test_run_id)
        connection.execute(
            """
            INSERT INTO deployment_releases (
                id, artifact_id, artifact_version_id, provider, status,
                url, error_code, test_run_id, created_at, published_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL)
            """,
            (release_id, artifact_id, artifact_version_id, provider, status, test_run_id, now),
        )
        record_event(
            connection,
            conversation_id=str(artifact_version["conversation_id"]),
            artifact_id=artifact_id,
            deployment_id=release_id,
            event_type="deployment_release.created",
            payload={
                "deployment_id": release_id,
                "release_id": release_id,
                "artifact_id": artifact_id,
                "artifact_version_id": artifact_version_id,
                "provider": provider,
                "status": status,
            },
            created_at=now,
        )
    return get_deployment_release(release_id, test_run_id=test_run_id)


def update_deployment_release(
    release_id: str,
    *,
    status: str,
    url: str | None,
    error_code: str | None,
    test_run_id: str,
) -> dict[str, object]:
    if status not in DEPLOYMENT_RELEASE_STATUSES:
        raise ValidationError("Unsupported deployment release status.", code="deployment_release_invalid")
    now = utc_now()
    published_at = now if status == "published" else None
    with connect() as connection:
        ensure_deployment_tables(connection)
        existing = _release_row(connection, release_id, test_run_id=test_run_id)
        artifact_context = _artifact_context(connection, str(existing["artifact_id"]), test_run_id=test_run_id)
        connection.execute(
            """
            UPDATE deployment_releases
            SET status = ?, url = ?, error_code = ?, published_at = ?
            WHERE id = ? AND test_run_id = ?
            """,
            (status, url, error_code, published_at or existing["published_at"], release_id, test_run_id),
        )
        if status in {"published", "failed"}:
            record_event(
                connection,
                conversation_id=str(artifact_context["conversation_id"]),
                artifact_id=str(existing["artifact_id"]),
                deployment_id=release_id,
                event_type=f"deployment_release.{status}",
                payload={
                    "deployment_id": release_id,
                    "release_id": release_id,
                    "artifact_id": existing["artifact_id"],
                    "artifact_version_id": existing["artifact_version_id"],
                    "provider": existing["provider"],
                    "status": status,
                    "url": url,
                    "error_code": error_code,
                },
                created_at=now,
            )
    return get_deployment_release(release_id, test_run_id=test_run_id)


def get_deployment_release(release_id: str, *, test_run_id: str) -> dict[str, object]:
    with connect() as connection:
        ensure_deployment_tables(connection)
        row = _release_row(connection, release_id, test_run_id=test_run_id)
    return deployment_release_to_response(_release_from_row(row))


def list_deployment_releases(
    *,
    test_run_id: str,
    conversation_id: str | None = None,
    artifact_id: str | None = None,
) -> list[dict[str, object]]:
    filters = ["dr.test_run_id = ?"]
    params: list[object] = [test_run_id]
    if conversation_id:
        filters.append("a.conversation_id = ?")
        params.append(conversation_id)
    if artifact_id:
        filters.append("dr.artifact_id = ?")
        params.append(artifact_id)
    with connect() as connection:
        ensure_deployment_tables(connection)
        rows = connection.execute(
            f"""
            SELECT dr.*
            FROM deployment_releases dr
            JOIN artifacts a ON a.id = dr.artifact_id AND a.test_run_id = dr.test_run_id
            WHERE {" AND ".join(filters)}
            ORDER BY dr.created_at ASC, dr.id ASC
            """,
            params,
        ).fetchall()
    return [deployment_release_to_response(_release_from_row(row)) for row in rows]


def ensure_deployment_tables(connection: Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS deployment_releases (
            id TEXT PRIMARY KEY,
            artifact_id TEXT NOT NULL,
            artifact_version_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('created', 'publishing', 'published', 'failed')),
            url TEXT,
            error_code TEXT,
            test_run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            published_at TEXT,
            FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
            FOREIGN KEY (artifact_version_id) REFERENCES artifact_versions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_deployment_releases_artifact
            ON deployment_releases(test_run_id, artifact_id, created_at ASC);
        CREATE INDEX IF NOT EXISTS idx_deployment_releases_status
            ON deployment_releases(test_run_id, status, created_at ASC);
        """
    )


def _artifact_version_row(connection: Connection, artifact_id: str, artifact_version_id: str, *, test_run_id: str) -> Row:
    row = connection.execute(
        """
            SELECT
                av.*,
                a.conversation_id AS conversation_id
            FROM artifact_versions av
            JOIN artifacts a ON a.id = av.artifact_id
            WHERE av.id = ?
            AND av.artifact_id = ?
            AND av.test_run_id = ?
            AND a.test_run_id = ?
        """,
        (artifact_version_id, artifact_id, test_run_id, test_run_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("ArtifactVersion not found.")
    return row


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


def _release_row(connection: Connection, release_id: str, *, test_run_id: str) -> Row:
    row = connection.execute(
        "SELECT * FROM deployment_releases WHERE id = ? AND test_run_id = ?",
        (release_id, test_run_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("DeploymentRelease not found.")
    return row


def _release_from_row(row: Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "artifact_id": row["artifact_id"],
        "artifact_version_id": row["artifact_version_id"],
        "provider": row["provider"],
        "status": row["status"],
        "url": row["url"],
        "error_code": row["error_code"],
        "created_at": row["created_at"],
        "published_at": row["published_at"],
    }
