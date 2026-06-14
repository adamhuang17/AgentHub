from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from services.api.app.shared.settings import get_settings


_INIT_LOCK = threading.Lock()
_INITIALIZED_PATHS: set[Path] = set()


def database_path() -> Path:
    return get_settings().db_path


def connect() -> sqlite3.Connection:
    path = database_path()
    _ensure_initialized(path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _ensure_initialized(path: Path) -> None:
    resolved = path.resolve()
    if resolved in _INITIALIZED_PATHS:
        return

    with _INIT_LOCK:
        if resolved in _INITIALIZED_PATHS:
            return
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(resolved) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    avatar TEXT,
                    avatar_url TEXT,
                    initials TEXT,
                    capability_tags_json TEXT NOT NULL,
                    adapter_kind TEXT,
                    system_prompt TEXT,
                    model TEXT,
                    api_base TEXT,
                    credential_source TEXT,
                    executable_path TEXT,
                    kind TEXT NOT NULL DEFAULT 'profile',
                    allowed_tools_json TEXT NOT NULL DEFAULT '[]',
                    execution_enabled INTEGER NOT NULL DEFAULT 0,
                    configured INTEGER NOT NULL DEFAULT 0,
                    health_status TEXT NOT NULL DEFAULT 'profile_only',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_credentials (
                    agent_id TEXT NOT NULL,
                    secret_name TEXT NOT NULL,
                    secret_value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (agent_id, secret_name),
                    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    test_run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_active_at TEXT NOT NULL,
                    archived_at TEXT
                );

                CREATE TABLE IF NOT EXISTS conversation_members (
                    conversation_id TEXT NOT NULL,
                    member_type TEXT NOT NULL,
                    member_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (conversation_id, member_type, member_id),
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    sender_type TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    mentions_json TEXT NOT NULL DEFAULT '[]',
                    references_json TEXT NOT NULL DEFAULT '[]',
                    reply_to_id TEXT,
                    created_by_run_id TEXT,
                    test_run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    created_by_message_id TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    test_run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                    FOREIGN KEY (created_by_message_id) REFERENCES messages(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    test_run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS plan_steps (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    assigned_agent_id TEXT,
                    status TEXT NOT NULL,
                    dispatch_source TEXT NOT NULL,
                    dispatch_reason TEXT NOT NULL,
                    blocked_reason TEXT,
                    depends_on_json TEXT NOT NULL,
                    expected_output_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE,
                    FOREIGN KEY (assigned_agent_id) REFERENCES agents(id)
                );

                CREATE INDEX IF NOT EXISTS idx_conversations_test_run_last_active
                    ON conversations(test_run_id, archived_at, last_active_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
                    ON messages(conversation_id, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_tasks_conversation_created
                    ON tasks(conversation_id, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_plans_task
                    ON plans(task_id, version DESC);
                CREATE INDEX IF NOT EXISTS idx_plan_steps_plan
                    ON plan_steps(plan_id, created_at ASC);

                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    source_type TEXT NOT NULL CHECK (source_type IN ('message', 'plan_step')),
                    source_message_id TEXT,
                    plan_step_id TEXT,
                    target_agent_id TEXT NOT NULL,
                    run_mode TEXT NOT NULL CHECK (run_mode IN ('direct_response', 'planned_step')),
                    status TEXT NOT NULL CHECK (status IN ('created', 'running', 'failed', 'succeeded', 'cancelled', 'incomplete', 'final_content_empty')),
                    error_code TEXT,
                    test_run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK (
                        (
                            source_type = 'message'
                            AND run_mode = 'direct_response'
                            AND source_message_id IS NOT NULL
                            AND plan_step_id IS NULL
                        )
                        OR
                        (
                            source_type = 'plan_step'
                            AND run_mode = 'planned_step'
                            AND plan_step_id IS NOT NULL
                        )
                    ),
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                    FOREIGN KEY (source_message_id) REFERENCES messages(id) ON DELETE CASCADE,
                    FOREIGN KEY (plan_step_id) REFERENCES plan_steps(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_agent_id) REFERENCES agents(id)
                );

                CREATE TABLE IF NOT EXISTS agent_run_events (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    type TEXT NOT NULL CHECK (
                        type IN (
                            'run_created',
                            'run_started',
                            'adapter_preflight_started',
                            'adapter_preflight_succeeded',
                            'adapter_preflight_failed',
                            'adapter_process_started',
                            'adapter_error',
                            'provider_not_configured',
                            'backend_session_started',
                            'backend_retry',
                            'assistant_message_delta',
                            'assistant_message_completed',
                            'artifact_created',
                            'stdout_line',
                            'stderr_line',
                            'raw_backend_event',
                            'usage_reported',
                            'run_timed_out',
                            'run_failed',
                            'run_succeeded'
                        )
                    ),
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (run_id, sequence),
                    FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation_created
                    ON agent_runs(conversation_id, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_source_message
                    ON agent_runs(source_message_id);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_plan_step
                    ON agent_runs(plan_step_id);
                CREATE INDEX IF NOT EXISTS idx_agent_run_events_run_sequence
                    ON agent_run_events(run_id, sequence ASC);
                """
            )
            _ensure_columns(
                connection,
                "agents",
                {
                    "avatar_url": "TEXT",
                    "adapter_kind": "TEXT",
                    "system_prompt": "TEXT",
                    "model": "TEXT",
                    "api_base": "TEXT",
                    "credential_source": "TEXT",
                    "executable_path": "TEXT",
                    "kind": "TEXT NOT NULL DEFAULT 'profile'",
                    "allowed_tools_json": "TEXT NOT NULL DEFAULT '[]'",
                    "execution_enabled": "INTEGER NOT NULL DEFAULT 0",
                    "configured": "INTEGER NOT NULL DEFAULT 0",
                    "health_status": "TEXT NOT NULL DEFAULT 'profile_only'",
                },
            )
            _ensure_columns(
                connection,
                "messages",
                {
                    "mentions_json": "TEXT NOT NULL DEFAULT '[]'",
                    "references_json": "TEXT NOT NULL DEFAULT '[]'",
                    "reply_to_id": "TEXT",
                    "created_by_run_id": "TEXT",
                },
            )
            _ensure_plan_steps_schema(connection)
            _ensure_agent_runs_schema(connection)
            _ensure_agent_run_events_schema(connection)
            _seed_agent_profiles(connection)
        _INITIALIZED_PATHS.add(resolved)


def _ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _ensure_plan_steps_schema(connection: sqlite3.Connection) -> None:
    columns = list(connection.execute("PRAGMA table_info(plan_steps)"))
    if not columns:
        return
    by_name = {row[1]: row for row in columns}
    assigned_not_null = bool(by_name["assigned_agent_id"][3])
    has_blocked_reason = "blocked_reason" in by_name
    if not assigned_not_null and has_blocked_reason:
        return

    connection.executescript(
        """
        DROP INDEX IF EXISTS idx_plan_steps_plan;
        ALTER TABLE plan_steps RENAME TO plan_steps_legacy;

        CREATE TABLE plan_steps (
            id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            assigned_agent_id TEXT,
            status TEXT NOT NULL,
            dispatch_source TEXT NOT NULL,
            dispatch_reason TEXT NOT NULL,
            blocked_reason TEXT,
            depends_on_json TEXT NOT NULL,
            expected_output_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE,
            FOREIGN KEY (assigned_agent_id) REFERENCES agents(id)
        );

        INSERT INTO plan_steps (
            id, plan_id, kind, assigned_agent_id, status, dispatch_source,
            dispatch_reason, blocked_reason, depends_on_json, expected_output_json,
            created_at
        )
        SELECT
            id, plan_id, kind, assigned_agent_id, status, dispatch_source,
            dispatch_reason, NULL, depends_on_json, expected_output_json,
            created_at
        FROM plan_steps_legacy;

        DROP TABLE plan_steps_legacy;

        CREATE INDEX IF NOT EXISTS idx_plan_steps_plan
            ON plan_steps(plan_id, created_at ASC);
        """
    )


def _ensure_agent_run_events_schema(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'agent_run_events'"
    ).fetchone()
    if row is None or row[0] is None:
        return
    sql = str(row[0])
    required_events = {
        "adapter_preflight_started",
        "adapter_preflight_succeeded",
        "adapter_preflight_failed",
        "adapter_process_started",
        "backend_session_started",
        "backend_retry",
        "stdout_line",
        "stderr_line",
        "raw_backend_event",
        "usage_reported",
        "run_timed_out",
        "artifact_created",
    }
    if all(event in sql for event in required_events):
        return

    connection.executescript(
        """
        DROP INDEX IF EXISTS idx_agent_run_events_run_sequence;
        ALTER TABLE agent_run_events RENAME TO agent_run_events_legacy;

        CREATE TABLE agent_run_events (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            type TEXT NOT NULL CHECK (
                type IN (
                    'run_created',
                    'run_started',
                    'adapter_preflight_started',
                    'adapter_preflight_succeeded',
                    'adapter_preflight_failed',
                    'adapter_process_started',
                    'adapter_error',
                    'provider_not_configured',
                    'backend_session_started',
                    'backend_retry',
                    'assistant_message_delta',
                    'assistant_message_completed',
                    'artifact_created',
                    'stdout_line',
                    'stderr_line',
                    'raw_backend_event',
                    'usage_reported',
                    'run_timed_out',
                    'run_failed',
                    'run_succeeded'
                )
            ),
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (run_id, sequence),
            FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        INSERT INTO agent_run_events (
            id, run_id, conversation_id, sequence, type, payload_json, created_at
        )
        SELECT
            id, run_id, conversation_id, sequence, type, payload_json, created_at
        FROM agent_run_events_legacy;

        DROP TABLE agent_run_events_legacy;

        CREATE INDEX IF NOT EXISTS idx_agent_run_events_run_sequence
            ON agent_run_events(run_id, sequence ASC);
        """
    )


def _ensure_agent_runs_schema(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'agent_runs'"
    ).fetchone()
    if row is None or row[0] is None:
        return
    current_sql = str(row[0])
    if "plan_steps_legacy" not in current_sql and "final_content_empty" in current_sql:
        return

    has_events = (
        connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'agent_run_events'"
        ).fetchone()
        is not None
    )
    connection.execute("PRAGMA foreign_keys = OFF")
    if has_events:
        connection.execute("ALTER TABLE agent_run_events RENAME TO agent_run_events_legacy_fk")
    connection.executescript(
        """
        DROP INDEX IF EXISTS idx_agent_runs_conversation_created;
        DROP INDEX IF EXISTS idx_agent_runs_source_message;
        DROP INDEX IF EXISTS idx_agent_runs_plan_step;
        ALTER TABLE agent_runs RENAME TO agent_runs_legacy_fk;

        CREATE TABLE agent_runs (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            source_type TEXT NOT NULL CHECK (source_type IN ('message', 'plan_step')),
            source_message_id TEXT,
            plan_step_id TEXT,
            target_agent_id TEXT NOT NULL,
            run_mode TEXT NOT NULL CHECK (run_mode IN ('direct_response', 'planned_step')),
            status TEXT NOT NULL CHECK (status IN ('created', 'running', 'failed', 'succeeded', 'cancelled', 'incomplete', 'final_content_empty')),
            error_code TEXT,
            test_run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (
                (
                    source_type = 'message'
                    AND run_mode = 'direct_response'
                    AND source_message_id IS NOT NULL
                    AND plan_step_id IS NULL
                )
                OR
                (
                    source_type = 'plan_step'
                    AND run_mode = 'planned_step'
                    AND plan_step_id IS NOT NULL
                )
            ),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (source_message_id) REFERENCES messages(id) ON DELETE CASCADE,
            FOREIGN KEY (plan_step_id) REFERENCES plan_steps(id) ON DELETE CASCADE,
            FOREIGN KEY (target_agent_id) REFERENCES agents(id)
        );

        INSERT INTO agent_runs (
            id, conversation_id, source_type, source_message_id, plan_step_id,
            target_agent_id, run_mode, status, error_code, test_run_id,
            created_at, updated_at
        )
        SELECT
            id, conversation_id, source_type, source_message_id, plan_step_id,
            target_agent_id, run_mode, status, error_code, test_run_id,
            created_at, updated_at
        FROM agent_runs_legacy_fk;

        DROP TABLE agent_runs_legacy_fk;

        CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation_created
            ON agent_runs(conversation_id, created_at ASC);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_source_message
            ON agent_runs(source_message_id);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_plan_step
            ON agent_runs(plan_step_id);
        """
    )
    if has_events:
        connection.executescript(
            """
            DROP INDEX IF EXISTS idx_agent_run_events_run_sequence;
            CREATE TABLE agent_run_events (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                type TEXT NOT NULL CHECK (
                    type IN (
                        'run_created',
                        'run_started',
                        'adapter_preflight_started',
                        'adapter_preflight_succeeded',
                        'adapter_preflight_failed',
                        'adapter_process_started',
                        'adapter_error',
                        'provider_not_configured',
                        'backend_session_started',
                        'backend_retry',
                        'assistant_message_delta',
                        'assistant_message_completed',
                        'artifact_created',
                        'stdout_line',
                        'stderr_line',
                        'raw_backend_event',
                        'usage_reported',
                        'run_timed_out',
                        'run_failed',
                        'run_succeeded'
                    )
                ),
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (run_id, sequence),
                FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            INSERT INTO agent_run_events (
                id, run_id, conversation_id, sequence, type, payload_json, created_at
            )
            SELECT
                id, run_id, conversation_id, sequence, type, payload_json, created_at
            FROM agent_run_events_legacy_fk;

            DROP TABLE agent_run_events_legacy_fk;

            CREATE INDEX IF NOT EXISTS idx_agent_run_events_run_sequence
                ON agent_run_events(run_id, sequence ASC);
            """
        )
    connection.execute("PRAGMA foreign_keys = ON")


def _seed_agent_profiles(connection: sqlite3.Connection) -> None:
    seed_profiles = [
        (
            "agent-demo-model",
            "Demo Model Agent",
            "custom_openai",
            "AI",
            '["direct_response", "chat", "model"]',
        ),
        (
            "agent-codex-profile",
            "Codex Profile",
            "codex",
            "CP",
            '["code", "review", "workspace"]',
        ),
        (
            "agent-claude-profile",
            "Claude Code Profile",
            "anthropic",
            "CC",
            '["code", "reasoning", "documents"]',
        ),
        (
            "demo_seed-opencode-profile",
            "AgentHub Coding Agent",
            "opencode",
            "AH",
            '["code", "implementation", "review", "workspace", "deploy"]',
        ),
    ]
    for agent_id, name, provider, initials, tags in seed_profiles:
        connection.execute(
            """
            INSERT OR IGNORE INTO agents (
                id, name, provider, avatar, initials, capability_tags_json,
                execution_enabled, configured, health_status,
                enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, NULL, ?, ?, 0, 0, 'profile_only', 1,
                '1970-01-01T00:00:00.000000Z',
                '1970-01-01T00:00:00.000000Z'
            )
            """,
            (agent_id, name, provider, initials, tags),
        )
