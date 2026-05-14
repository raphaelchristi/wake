"""initial wake schema (postgres backend)

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-13 00:00:00.000000

Creates the four canonical tables (agents, agent_versions,
environments, sessions) plus a HASH-partitioned ``events`` parent with
N partitions (configurable via ``WAKE_PG_EVENT_PARTITIONS`` env var,
default 16). Also installs:

  * BRIN index on ``events.created_at`` (cheap range scans).
  * btree index on ``(session_id, seq)`` per partition (fast tailing).
  * AFTER INSERT trigger that emits ``pg_notify('events_<id_short>',
    payload)`` for the LISTEN/NOTIFY-driven subscribe() path.

Channel names follow the convention::

    events_<first 12 chars of session_id, lowercased>

which keeps us within Postgres' 63-byte ``NAMEDATALEN`` limit even with
the ``events_`` prefix.

The migration is idempotent (CREATE ... IF NOT EXISTS where possible)
and downable.
"""

from __future__ import annotations

import os

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _partition_count() -> int:
    """Read partition count from env, with a safe default."""
    raw = os.environ.get("WAKE_PG_EVENT_PARTITIONS", "16")
    try:
        n = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"WAKE_PG_EVENT_PARTITIONS must be an integer, got {raw!r}") from exc
    if n < 1:
        raise RuntimeError(f"WAKE_PG_EVENT_PARTITIONS must be >= 1, got {n}")
    return n


def upgrade() -> None:
    n = _partition_count()

    # ------------------------------------------------------------------
    # agents + agent_versions
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agents (
            id              VARCHAR(26) PRIMARY KEY,
            organization_id TEXT NOT NULL DEFAULT 'default',
            workspace_id    TEXT NOT NULL DEFAULT 'default',
            name            TEXT NOT NULL,
            current_version INTEGER NOT NULL DEFAULT 1,
            created_at      TIMESTAMPTZ NOT NULL,
            archived_at     TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_versions (
            agent_id      VARCHAR(26) NOT NULL
                           REFERENCES agents(id) ON DELETE CASCADE,
            version       INTEGER NOT NULL,
            name          TEXT NOT NULL,
            model         JSONB NOT NULL,
            system        TEXT,
            tools         JSONB NOT NULL DEFAULT '[]'::jsonb,
            mcp_servers   JSONB NOT NULL DEFAULT '[]'::jsonb,
            skills        JSONB NOT NULL DEFAULT '[]'::jsonb,
            description   TEXT,
            meta          JSONB NOT NULL DEFAULT '{}'::jsonb,
            content_hash  VARCHAR(64) NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (agent_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_agents_workspace
            ON agents (workspace_id)
        """
    )

    # ------------------------------------------------------------------
    # environments
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS environments (
            id          VARCHAR(26) PRIMARY KEY,
            organization_id TEXT NOT NULL DEFAULT 'default',
            workspace_id    TEXT NOT NULL DEFAULT 'default',
            name        TEXT NOT NULL,
            config      JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL,
            archived_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_environments_workspace
            ON environments (workspace_id)
        """
    )

    # ------------------------------------------------------------------
    # sessions
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id              VARCHAR(26) PRIMARY KEY,
            organization_id TEXT NOT NULL DEFAULT 'default',
            workspace_id    TEXT NOT NULL DEFAULT 'default',
            agent_id        VARCHAR(26) NOT NULL,
            agent_version   INTEGER NOT NULL,
            environment_id  VARCHAR(26),
            status          TEXT NOT NULL DEFAULT 'idle',
            container_id    TEXT,
            workspace_path  TEXT,
            meta            JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL,
            updated_at      TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_sessions_status
            ON sessions (status)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_sessions_workspace_status
            ON sessions (workspace_id, status)
        """
    )

    # ------------------------------------------------------------------
    # events (HASH-partitioned)
    # ------------------------------------------------------------------
    # The parent table holds no data on its own; rows live in the
    # ``events_p_NN`` partition selected by HASH(session_id).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id          VARCHAR(26) NOT NULL,
            organization_id TEXT NOT NULL DEFAULT 'default',
            workspace_id    TEXT NOT NULL DEFAULT 'default',
            session_id  VARCHAR(26) NOT NULL,
            seq         INTEGER NOT NULL,
            type        TEXT NOT NULL,
            payload     JSONB NOT NULL,
            parent_id   VARCHAR(26),
            meta        JSONB,
            created_at  TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (id, session_id)
        ) PARTITION BY HASH (session_id)
        """
    )
    for i in range(n):
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS events_p_{i:02d}
            PARTITION OF events
            FOR VALUES WITH (MODULUS {n}, REMAINDER {i})
            """
        )
        # Per-partition indexes (PG creates them on the parent too via
        # ATTACH semantics, but explicit per-partition indexes give
        # predictable plans and tooling support).
        op.execute(
            f"""
            CREATE INDEX IF NOT EXISTS ix_events_p_{i:02d}_session_seq
            ON events_p_{i:02d} (session_id, seq)
            """
        )
        op.execute(
            f"""
            CREATE INDEX IF NOT EXISTS ix_events_p_{i:02d}_workspace_session_seq
            ON events_p_{i:02d} (workspace_id, session_id, seq)
            """
        )
        op.execute(
            f"""
            CREATE INDEX IF NOT EXISTS ix_events_p_{i:02d}_parent
            ON events_p_{i:02d} (parent_id)
            """
        )
        # BRIN on created_at — tiny, cheap to maintain, ideal for the
        # append-only insert pattern.
        op.execute(
            f"""
            CREATE INDEX IF NOT EXISTS brin_events_p_{i:02d}_created_at
            ON events_p_{i:02d} USING BRIN (created_at)
            """
        )

    # Uniqueness on (session_id, seq): partitions are routed by
    # HASH(session_id) so all rows for a given session live on one
    # partition. A per-partition unique index therefore enforces the
    # global invariant.
    for i in range(n):
        op.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_events_p_{i:02d}_session_seq
            ON events_p_{i:02d} (session_id, seq)
            """
        )

    # ------------------------------------------------------------------
    # NOTIFY trigger
    # ------------------------------------------------------------------
    # Channel name: ``events_<first 12 hex chars of session_id>``.
    # session_id is a ULID (26 chars, Crockford base32). We lowercase
    # the prefix so Postgres' channel-name folding is a no-op.
    #
    # Payload is the new event id — small enough to fit Postgres'
    # 8000-byte NOTIFY payload limit comfortably.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION wake_events_notify() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            channel TEXT;
        BEGIN
            channel := 'events_' || lower(substring(NEW.session_id from 1 for 12));
            PERFORM pg_notify(channel, NEW.id::text);
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS wake_events_notify_trg ON events;
        CREATE TRIGGER wake_events_notify_trg
        AFTER INSERT ON events
        FOR EACH ROW
        EXECUTE FUNCTION wake_events_notify();
        """
    )


def downgrade() -> None:
    n = _partition_count()
    op.execute("DROP TRIGGER IF EXISTS wake_events_notify_trg ON events")
    op.execute("DROP FUNCTION IF EXISTS wake_events_notify()")
    for i in range(n):
        op.execute(f"DROP TABLE IF EXISTS events_p_{i:02d} CASCADE")
    op.execute("DROP TABLE IF EXISTS events CASCADE")
    op.execute("DROP TABLE IF EXISTS sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS environments CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS agents CASCADE")
