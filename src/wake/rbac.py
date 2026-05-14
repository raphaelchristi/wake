"""Role-based access control primitives.

Wake's RBAC layer is intentionally minimal: three fixed roles
(``admin`` / ``operator`` / ``viewer``) bound to ``(user_id,
workspace_id)`` pairs. Roles gate **writes**; reads are open to every
role (within tenancy isolation — see ``wake.tenancy``).

Design decisions (locked by PHASE-6-CONTRACT.md):

* Roles are an ``Enum`` — three values, no custom roles in this phase.
* Enforcement happens at the route boundary via
  ``Depends(require_role(...))``. Handlers never inline-check.
* The ``WAKE_RBAC_ENABLED`` env var gates enforcement. With the flag
  off (default) Wake stays in single-user mode: ``get_current_user``
  returns :func:`User.system` and ``require_role`` accepts every call.
  This keeps Phase 6 zero-friction for existing single-tenant
  deployments.
* User identity is delivered via the ``X-Wake-User-Id`` header. The
  gateway / IdP in front of Wake is expected to inject it after its
  own auth pass. We deliberately do **not** ship a password store —
  OAuth / SAML / mTLS integrations land in a later phase.

This module is import-safe (no FastAPI dependency) so the enum and
:class:`User` can be reused by the stores and the test suite without
pulling the web layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003 — runtime value for User.created_at
from enum import Enum


class Role(str, Enum):  # noqa: UP042 — StrEnum is 3.11+ but plain `str, Enum` is forward-compatible
    """Wake RBAC roles.

    The string values are stable on-the-wire identifiers — never
    rename them (migrations would have to backfill ``user_roles``
    rows). New roles must be added at the *end* of the enum so
    ordering remains stable.
    """

    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"

    @classmethod
    def parse(cls, raw: str) -> Role:
        """Parse a string into a :class:`Role`.

        Accepts both the canonical lower-case form and any case (the
        gateway may upper-case headers). Raises ``ValueError`` for an
        unknown role so callers can surface a 400.
        """
        if not raw:
            raise ValueError("role cannot be empty")
        normalized = raw.strip().lower()
        for role in cls:
            if role.value == normalized:
                return role
        raise ValueError(f"unknown role: {raw!r}")

    def permits(self, action: Action) -> bool:
        """Return True if this role is allowed to perform ``action``.

        The matrix is intentionally explicit (no inheritance) so each
        cell can be audited. The cases:

        ============== =========================================
        Action         Permitted roles
        ============== =========================================
        ``read``       admin, operator, viewer
        ``write``      admin, operator
        ``admin``      admin
        ``rotate``     admin
        ============== =========================================

        ``rotate`` is a stricter form of ``write`` reserved for vault
        credential rotation / revocation — operators read audit, admins
        rotate / revoke.
        """
        if action == "read":
            return True  # every role can read
        if action == "write":
            return self in (Role.ADMIN, Role.OPERATOR)
        if action == "admin":
            return self == Role.ADMIN
        if action == "rotate":
            return self == Role.ADMIN
        raise ValueError(f"unknown action: {action!r}")


# Coarse action vocabulary used by ``Role.permits``. Kept as a plain
# string literal type so callers don't have to import an enum just to
# ask a permission question.
Action = str  # one of: "read" | "write" | "admin" | "rotate"


@dataclass(frozen=True)
class User:
    """Identity carried alongside the tenant context on every request.

    ``id`` is the stable identifier the gateway injects via
    ``X-Wake-User-Id``. ``display_name`` is operator-facing only
    (audit logs, dashboard). ``roles`` lists role assignments scoped
    to the current workspace — Wake resolves the workspace at the
    request boundary and never crosses scopes.

    The ``system`` factory returns the sentinel identity used when
    RBAC is disabled. ``id == "system"`` is reserved and rejected by
    :class:`UserStore.create`.
    """

    id: str
    display_name: str | None = None
    roles: tuple[Role, ...] = field(default_factory=tuple)
    organization_id: str = "default"
    workspace_id: str = "default"
    created_at: datetime | None = None

    @classmethod
    def system(
        cls,
        *,
        organization_id: str = "default",
        workspace_id: str = "default",
    ) -> User:
        """Sentinel user used when RBAC is disabled.

        The system user holds every role so ``require_role`` accepts
        any call. Stores reject persistence of the sentinel.
        """
        return cls(
            id="system",
            display_name="system",
            roles=(Role.ADMIN, Role.OPERATOR, Role.VIEWER),
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    def has_role(self, *roles: Role) -> bool:
        """True if the user holds any of the listed roles."""
        if not roles:
            return False
        return any(r in self.roles for r in roles)

    def with_roles(self, roles: tuple[Role, ...]) -> User:
        """Return a copy with the role tuple replaced.

        Convenient for ``UserStore.get`` implementations that load
        the row first and the roles second.
        """
        return User(
            id=self.id,
            display_name=self.display_name,
            roles=tuple(roles),
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            created_at=self.created_at,
        )


# Env var names — exported so the API dependency layer can stay
# free of magic strings.
WAKE_RBAC_ENABLED_ENV = "WAKE_RBAC_ENABLED"
WAKE_USER_ID_HEADER = "X-Wake-User-Id"


def is_rbac_enabled() -> bool:
    """Return True when ``WAKE_RBAC_ENABLED`` is a truthy string.

    Accepts ``1``/``true``/``yes``/``on`` (case-insensitive). Any
    other value — including empty — disables enforcement and keeps
    the API in zero-friction single-user mode.
    """
    import os

    raw = os.environ.get(WAKE_RBAC_ENABLED_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


__all__ = [
    "Role",
    "Action",
    "User",
    "WAKE_RBAC_ENABLED_ENV",
    "WAKE_USER_ID_HEADER",
    "is_rbac_enabled",
]
