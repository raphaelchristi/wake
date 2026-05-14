"""Idempotency: events.idempotency_key column + UNIQUE partial index.

Revision ID: 0004_idempotency
Revises: 0003_rbac
Create Date: 2026-05-14

Phase 7 — Tier 1 gap #4 (worker double-process dedupe + client retry
safety).

Schema change
-------------

* Adds nullable ``events.idempotency_key TEXT`` column. NULL values
  preserve the historical behaviour (every append creates a new row).
* Installs a per-partition UNIQUE partial index on
  ``(workspace_id, session_id, idempotency_key)
   WHERE idempotency_key IS NOT NULL``. The ``events`` parent is
  HASH-partitioned on ``session_id`` so the per-session uniqueness
  invariant is preserved on each partition — every row for a given
  session lives on exactly one partition.

Both upgrade and downgrade are idempotent (IF (NOT) EXISTS) so
re-running on a partially-migrated database is safe.

Postgres version note
---------------------

PG 11+ supports partial unique indexes on partitioned tables only
when the partition key is a subset of the index columns. We satisfy
that by including ``session_id`` (the HASH partition key) inside the
unique tuple — Postgres recognises this and installs the index across
all partitions.
"""

from __future__ import annotations

import os

from alembic import op

revision = "0005_idempotency"
down_revision = "0004_system_user_constraint"
branch_labels = None
depends_on = None


def _partition_count() -> int:
    raw = os.environ.get("WAKE_PG_EVENT_PARTITIONS", "16")
    try:
        n = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"WAKE_PG_EVENT_PARTITIONS must be int, got {raw!r}") from exc
    if n < 1:
        raise RuntimeError(f"WAKE_PG_EVENT_PARTITIONS must be >= 1, got {n}")
    return n


def upgrade() -> None:
    # Add the column. ALTER TABLE ... ADD COLUMN propagates to every
    # existing HASH partition via PG's inheritance semantics.
    op.execute(
        """
        ALTER TABLE events
            ADD COLUMN IF NOT EXISTS idempotency_key TEXT
        """
    )

    # Per-partition UNIQUE partial index. We index per-partition (not
    # on the parent) because HASH-partitioned UNIQUE indexes on the
    # parent require the partition key to be a prefix of the unique
    # columns — we'd need ``(session_id, workspace_id,
    # idempotency_key)``. Per-partition is simpler and equally
    # correct because every (workspace_id, session_id) tuple maps to
    # exactly one partition via the HASH(session_id) router.
    n = _partition_count()
    for i in range(n):
        op.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_events_p_{i:02d}_idempotency
                ON events_p_{i:02d} (workspace_id, session_id, idempotency_key)
                WHERE idempotency_key IS NOT NULL
            """
        )


def downgrade() -> None:
    n = _partition_count()
    for i in range(n):
        op.execute(
            f"DROP INDEX IF EXISTS uq_events_p_{i:02d}_idempotency"
        )
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS idempotency_key")
