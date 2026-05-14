"""Add first-class organization/workspace tenancy columns.

Revision ID: 0002_tenancy_columns
Revises: 0001_initial_schema
Create Date: 2026-05-14
"""

from __future__ import annotations

from alembic import op

revision = "0002_tenancy_columns"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("agents", "environments", "sessions", "events"):
        op.execute(
            f"""
            ALTER TABLE {table}
                ADD COLUMN IF NOT EXISTS organization_id TEXT NOT NULL DEFAULT 'default',
                ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT 'default'
            """
        )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_agents_workspace
            ON agents (workspace_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_environments_workspace
            ON environments (workspace_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_sessions_workspace_status
            ON sessions (workspace_id, status)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_events_workspace_session_seq
            ON events (workspace_id, session_id, seq)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_workspace_session_seq")
    op.execute("DROP INDEX IF EXISTS ix_sessions_workspace_status")
    op.execute("DROP INDEX IF EXISTS ix_environments_workspace")
    op.execute("DROP INDEX IF EXISTS ix_agents_workspace")

    for table in ("events", "sessions", "environments", "agents"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS workspace_id")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS organization_id")
