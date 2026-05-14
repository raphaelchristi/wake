"""RBAC: users + user_roles tables.

Revision ID: 0003_rbac
Revises: 0002_tenancy_columns
Create Date: 2026-05-14

Adds the two RBAC tables:

* ``users``       — workspace-scoped user catalog (composite PK
  ``(workspace_id, id)`` so the same id can live in two workspaces
  as independent principals).
* ``user_roles``  — many-to-many binding ``(workspace_id, user_id,
  role)`` so a user can hold any subset of roles in a workspace.

Both upgrade and downgrade are idempotent — IF NOT EXISTS / IF EXISTS
everywhere — so re-running on a partially-migrated database is safe.
Indexes:

* ``ix_users_workspace`` on ``users(workspace_id)`` for the workspace
  list query.
* ``ix_user_roles_user`` on ``user_roles(workspace_id, user_id)`` for
  the per-user roles lookup.
* ``ix_user_roles_role`` on ``user_roles(workspace_id, role)`` for
  reverse lookups (audit / find-all-admins).
"""

from __future__ import annotations

from alembic import op

revision = "0003_rbac"
down_revision = "0002_tenancy_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            workspace_id    TEXT NOT NULL,
            id              TEXT NOT NULL,
            organization_id TEXT NOT NULL DEFAULT 'default',
            display_name    TEXT,
            created_at      TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (workspace_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_users_workspace
            ON users (workspace_id)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_roles (
            workspace_id    TEXT NOT NULL,
            user_id         TEXT NOT NULL,
            role            TEXT NOT NULL,
            organization_id TEXT NOT NULL DEFAULT 'default',
            created_at      TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (workspace_id, user_id, role),
            FOREIGN KEY (workspace_id, user_id)
                REFERENCES users (workspace_id, id)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_roles_user
            ON user_roles (workspace_id, user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_roles_role
            ON user_roles (workspace_id, role)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_roles_role")
    op.execute("DROP INDEX IF EXISTS ix_user_roles_user")
    op.execute("DROP TABLE IF EXISTS user_roles CASCADE")
    op.execute("DROP INDEX IF EXISTS ix_users_workspace")
    op.execute("DROP TABLE IF EXISTS users CASCADE")
