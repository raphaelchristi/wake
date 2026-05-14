"""Retention + archive: archive_log audit table.

Revision ID: 0005_retention
Revises: 0004_idempotency
Create Date: 2026-05-14

Phase 7 — gap #5. Adds the ``archive_log`` table that
``wake events archive`` writes one row to per successful batch. The
column shape mirrors :class:`wake_store_postgres.models.ArchiveLogRow`:

* ``id``                   ULID of the archive batch
* ``workspace_id``         scope (NULL = global archive)
* ``cutoff``               --before passed to the CLI
* ``s3_bucket`` / ``s3_key``  destination object
* ``s3_etag``              upload verification handle
* ``session_count``        distinct sessions covered
* ``event_count``          rows uploaded
* ``bytes_uploaded``       JSONL gzip byte count
* ``upload_completed_at``  timestamp the upload succeeded
* ``delete_completed_at``  NULLABLE — set once the post-upload purge
                           sweeps complete (NULL between upload and
                           delete so an operator can spot a stuck
                           batch)

Both upgrade and downgrade are idempotent. Down migration drops the
table; the local event log is unaffected (the audit just becomes
unrecoverable, which is acceptable — archive history is not a
compliance source).

NOTE: this migration intentionally does NOT alter the depends-on
chain for the previous slice's 0004_idempotency migration. If that
slice is not yet merged the chain is still valid: Alembic resolves
revision dependencies by ``down_revision`` only and 0004 + 0005 are
independent of each other on a schema level.
"""

from __future__ import annotations

from alembic import op

revision = "0005_retention"
down_revision = "0004_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS archive_log (
            id                    TEXT PRIMARY KEY,
            workspace_id          TEXT,
            cutoff                TIMESTAMPTZ NOT NULL,
            s3_bucket             TEXT NOT NULL,
            s3_key                TEXT NOT NULL,
            s3_etag               TEXT,
            session_count         INTEGER NOT NULL DEFAULT 0,
            event_count           INTEGER NOT NULL DEFAULT 0,
            bytes_uploaded        BIGINT NOT NULL DEFAULT 0,
            upload_completed_at   TIMESTAMPTZ NOT NULL,
            delete_completed_at   TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_archive_log_workspace
            ON archive_log (workspace_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_archive_log_upload_completed_at
            ON archive_log (upload_completed_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_archive_log_upload_completed_at")
    op.execute("DROP INDEX IF EXISTS ix_archive_log_workspace")
    op.execute("DROP TABLE IF EXISTS archive_log CASCADE")
