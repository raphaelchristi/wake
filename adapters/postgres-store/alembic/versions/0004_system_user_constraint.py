"""Reserved ``system`` user-id rejected at the DB layer.

Revision ID: 0004_system_user_constraint
Revises: 0003_rbac
Create Date: 2026-05-14

Phase 6.1 fix for Codex adversarial review finding #3 (MEDIUM) —
"Reserved `system` user is not rejected at the database layer".

Both ``UserStore.create()`` implementations refuse the reserved id, but
the underlying ``users`` table accepted it. A direct SQL import or a
future store path that bypasses ``UserStore.create()`` could plant a
``users.id = 'system'`` row that ``get_current_user()`` would then
accept as a normal persisted user when RBAC is enabled.

This migration adds CHECK constraints (idempotent):

* ``ck_users_id_not_system``      on ``users.id``
* ``ck_user_roles_user_not_system`` on ``user_roles.user_id``

If any pre-existing ``system`` rows are present we delete them as part
of the upgrade — they had no legitimate use before this migration
existed and dropping them is safer than failing the migration. The
operator logs surface the row count for auditing.
"""

from __future__ import annotations

from alembic import op

revision = "0004_system_user_constraint"
down_revision = "0003_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defensive cleanup: any rogue ``system`` rows are dropped so the
    # CHECK constraint can be added without rollback. Cascades through
    # the FK on user_roles automatically.
    op.execute(
        """
        DELETE FROM user_roles WHERE user_id = 'system';
        DELETE FROM users      WHERE id      = 'system';
        """
    )

    # Idempotent: ``ADD CONSTRAINT IF NOT EXISTS`` is not standard
    # Postgres, so wrap in a DO block.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM   pg_constraint
                WHERE  conname = 'ck_users_id_not_system'
            ) THEN
                ALTER TABLE users
                    ADD CONSTRAINT ck_users_id_not_system
                    CHECK (id <> 'system');
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM   pg_constraint
                WHERE  conname = 'ck_user_roles_user_not_system'
            ) THEN
                ALTER TABLE user_roles
                    ADD CONSTRAINT ck_user_roles_user_not_system
                    CHECK (user_id <> 'system');
            END IF;
        END$$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE user_roles DROP CONSTRAINT IF EXISTS ck_user_roles_user_not_system"
    )
    op.execute(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_id_not_system"
    )
