# RBAC (Role-Based Access Control)

> Status: ✅ Shipped in Phase 6 (commit `agent/tenancy-rbac` branch).
> Tier 0 gap #2 closed.

Wake's RBAC layer is intentionally minimal: three fixed roles
(`admin` / `operator` / `viewer`) bound to `(user_id, workspace_id)`
pairs. Roles gate **writes**; reads are open to every role within a
workspace.

This document captures the contract end-to-end:

1. [Motivation](#motivation)
2. [Roles and permission matrix](#roles-and-permission-matrix)
3. [Header surface](#header-surface)
4. [Enablement flag](#enablement-flag)
5. [Per-route enforcement](#per-route-enforcement)
6. [Wire shapes](#wire-shapes)
7. [Stores and persistence](#stores-and-persistence)
8. [Migrations](#migrations)
9. [Integration patterns](#integration-patterns)
10. [Audit and observability](#audit-and-observability)
11. [Threat model](#threat-model)
12. [Operational runbook](#operational-runbook)
13. [Limitations and what is NOT shipped](#limitations-and-what-is-not-shipped)
14. [Future work](#future-work)

---

## Motivation

Single-tenant deployments do not need authorisation. Once Wake is in
front of more than one operator — even within the same organisation —
**writes** must be gated. The Phase 6 contract spelled the goal out as
Tier 0 gap #2: a minimum viable role layer that meets four constraints:

* **Disabled by default.** Existing dev mode keeps working with zero
  config (no header required, no DB row, no SQL migration to
  surface).
* **Per-route enforcement.** Gate is on the route signature
  (`Depends(require_role(...))`), not buried inside handlers. Easier
  to audit; harder to forget.
* **Workspace-scoped.** Role assignments belong to the workspace,
  matching the tenancy boundary already shipped in commit `89bec12`.
* **Pluggable identity.** Wake does NOT host passwords. The gateway
  / IdP in front of Wake injects `X-Wake-User-Id` after its own auth
  pass (OAuth, SAML, mTLS — operator's choice).

That last constraint is the load-bearing decision: Wake stays out of
the user-management business and trusts the gateway. This keeps the
core small and lets every deployment pick the IdP that fits its
estate. The cost is that operators must set up the gateway hop
correctly — see [Integration patterns](#integration-patterns).

---

## Roles and permission matrix

Roles are declared as `wake.rbac.Role`:

| Role       | Value (wire)  | Intent                       |
|------------|---------------|------------------------------|
| `ADMIN`    | `admin`       | Full control + user mgmt     |
| `OPERATOR` | `operator`    | CRUD on agents/sessions      |
| `VIEWER`   | `viewer`      | Read-only (SRE / observer)   |

The role string values are stable on the wire — never rename them or
the `user_roles` rows persisted by earlier deployments would have to
be backfilled.

`Role.permits(action)` exposes the coarse permission vocabulary that
mirrors the route gates:

| Action     | Permitted roles                  | Examples                              |
|------------|----------------------------------|---------------------------------------|
| `read`     | admin, operator, viewer          | `GET /v1/sessions`, `GET /v1/agents`  |
| `write`    | admin, operator                  | `POST /v1/agents`, `POST /v1/sessions`|
| `admin`    | admin                            | `POST /v1/users`, vault rotate        |
| `rotate`   | admin                            | `POST /v1/vault/credentials/.../rotate` |

`Role.permits` is intentionally explicit (no inheritance) — each cell
is auditable in isolation, and adding a new action does not silently
grant it to existing roles.

---

## Header surface

When RBAC is enabled the API expects three additional headers on top
of the existing API key + tenancy pair (see `docs/ARCHITECTURE.md`):

```
X-Wake-API-Key:          <key>          # exists since Phase 5.1
X-Wake-Organization-Id:  <org>          # exists since 89bec12
X-Wake-Workspace-Id:     <workspace>    # exists since 89bec12
X-Wake-User-Id:          <user_id>      # NEW (Phase 6)
```

`X-Wake-User-Id` is **only consulted when `WAKE_RBAC_ENABLED=true`**.
With the flag off the header is ignored and every request runs as the
`User.system()` sentinel.

| Scenario                                 | Status code              |
|------------------------------------------|--------------------------|
| RBAC off, no `X-Wake-User-Id`            | 200 (system user)        |
| RBAC on, no `X-Wake-User-Id`             | 401 `user id required`   |
| RBAC on, unknown `X-Wake-User-Id`        | 401 `unknown user`       |
| RBAC on, user lacks required role        | 403 `forbidden: ...`     |
| Cross-workspace request                  | 404 (tenancy opacity)    |
| RBAC on, store not configured            | 503 `user_store not configured` |

The 401/403/404 mapping is load-bearing:

* **404 cross-workspace** (from the tenancy layer) does not leak the
  existence of resources to outside principals.
* **403 cross-RBAC** signals that the principal is recognised but
  lacks the role. Differentiating 403 from 404 here is fine: the
  principal already passed tenancy isolation, so they have proof
  they are *inside* the workspace.

---

## Enablement flag

`WAKE_RBAC_ENABLED` is a single env var:

```bash
# Disabled (default) — back-compat dev mode.
WAKE_RBAC_ENABLED=false

# Enabled — every authenticated route enforces role gates.
WAKE_RBAC_ENABLED=true
```

Accepted truthy values (case-insensitive, whitespace trimmed):
`1`, `true`, `yes`, `on`. Anything else is treated as off.

The flag is read **per request** via `wake.rbac.is_rbac_enabled()`.
Changing it on a running cluster is safe — there is no cached lookup
that would require a restart. (You probably still want a deploy hop
so all replicas flip together, but Wake will not bite you if some
flip first.)

When RBAC is off:

* `get_current_user` returns `User.system()` with every role.
* `require_role(...)` accepts every request unchanged.
* The `/v1/users` CRUD routes still work — they remain admin-only
  but `User.system()` carries `ADMIN` so any caller can manage
  identities during the migration window.

When RBAC is on:

* `get_current_user` resolves `X-Wake-User-Id` via the
  `UserStore`; missing header → 401.
* `require_role(...)` fails closed: empty role intersection → 403.
* The `UserStore` must be wired in `create_app(user_store=...)` or
  every gated route returns 503.

---

## Per-route enforcement

Gates live on the route signature, not the handler body. The pattern
is:

```python
from fastapi import APIRouter, Depends
from wake.api.dependencies import require_role
from wake.rbac import Role

router = APIRouter(prefix="/v1/widgets", tags=["widgets"])

@router.post(
    "",
    dependencies=[Depends(require_role(Role.ADMIN, Role.OPERATOR))],
)
async def create_widget(...): ...
```

Adding a new write-gated endpoint is a single decorator line. The
`require_role` factory builds a fresh dependency per call so closure
state is never shared across routes.

The current Phase 6 matrix:

| Endpoint                                     | Method | Gate                                   |
|----------------------------------------------|--------|----------------------------------------|
| `/v1/agents`                                 | POST   | `require_role(ADMIN, OPERATOR)`        |
| `/v1/agents/{id}`                            | PATCH  | `require_role(ADMIN, OPERATOR)`        |
| `/v1/agents/{id}/archive`                    | POST   | `require_role(ADMIN, OPERATOR)`        |
| `/v1/agents` (list / get / versions)         | GET    | open (read-allowed roles only)         |
| `/v1/environments`                           | POST   | `require_role(ADMIN, OPERATOR)`        |
| `/v1/environments/{id}` archive / delete     | POST/DELETE | `require_role(ADMIN, OPERATOR)`   |
| `/v1/sessions`                               | POST   | `require_role(ADMIN, OPERATOR)`        |
| `/v1/sessions/{id}`                          | DELETE | `require_role(ADMIN, OPERATOR)`        |
| `/v1/sessions/{id}/interrupt|archive`        | POST   | `require_role(ADMIN, OPERATOR)`        |
| `/v1/sessions/{id}/events`                   | POST   | `require_role(ADMIN, OPERATOR)`        |
| `/v1/vault/oauth/start`                      | POST   | `require_role(ADMIN)`                  |
| `/v1/vault/credentials/{id}/rotate`          | POST   | `require_role(ADMIN)`                  |
| `/v1/vault/credentials/{id}`                 | DELETE | `require_role(ADMIN)`                  |
| `/v1/users` (CRUD)                           | *      | `require_role(ADMIN)` (writes)         |
| `/v1/users/me`                               | GET    | any authenticated principal            |
| `/v1/metrics/*` + `/v1/workers`              | GET    | open (read-allowed roles only)         |

Reads under `/v1/*` do not carry an explicit gate because they
already pass through `verify_api_key` + `get_tenant_context`. The
404 cross-workspace rule keeps them safe; an explicit
`require_role(*Role)` gate on reads is redundant noise.

---

## Wire shapes

### `POST /v1/users`

```http
POST /v1/users
X-Wake-User-Id: admin-bob
X-Wake-Workspace-Id: workspace_a
Content-Type: application/json

{
  "id": "alice",
  "display_name": "Alice Liddell",
  "roles": ["operator"]
}
```

→ `201`

```json
{
  "id": "alice",
  "display_name": "Alice Liddell",
  "organization_id": "default",
  "workspace_id": "workspace_a",
  "roles": ["operator"],
  "created_at": "2026-05-14T12:34:56Z"
}
```

`409 Conflict` when the user id already exists in the workspace.
`400 Bad Request` when the id is reserved (`system`).

### `POST /v1/users/{id}/roles`

```http
POST /v1/users/alice/roles
{ "role": "admin" }
```

Idempotent: re-assigning the same role returns `200` with the same
payload.

### `DELETE /v1/users/{id}/roles/{role}`

Idempotent: revoking a role the user does not hold is `200` (with
the unchanged role tuple). Revoking against a missing user is
`404`.

### `GET /v1/users/me`

Returns the caller's identity + role tuple. With RBAC off:

```json
{
  "id": "system",
  "display_name": "system",
  "organization_id": "default",
  "workspace_id": "default",
  "roles": ["admin", "operator", "viewer"],
  "created_at": null
}
```

---

## Stores and persistence

`UserStore` (in `wake.store.base`) is the Protocol every backend must
implement:

```python
class UserStore(ABC):
    async def create(self, user_id, *, display_name=None,
                     organization_id="default", workspace_id="default") -> User: ...
    async def get(self, user_id, *, workspace_id) -> User | None: ...
    async def list(self, *, workspace_id) -> list[User]: ...
    async def update(self, user_id, *, workspace_id, display_name=None) -> User: ...
    async def delete(self, user_id, *, workspace_id) -> None: ...
    async def assign_role(self, user_id, role, *, workspace_id) -> None: ...
    async def revoke_role(self, user_id, role, *, workspace_id) -> None: ...
    async def roles_for(self, user_id, *, workspace_id) -> list[Role]: ...
```

Two reference implementations ship in Phase 6:

* `wake.store.sqlite.SQLiteUserStore` — bundled into `SQLiteStore`.
  Tables: `users (workspace_id, id, ...)` + `user_roles (workspace_id,
  user_id, role, ...)`. Cascade-on-delete is handled in Python so the
  schema stays portable.
* `wake_store_postgres.PostgresUserStore` — bundled into
  `PostgresStore`. Same schema, plus a real FK with `ON DELETE
  CASCADE` so deletes are transactional inside Postgres.

The composite primary key on `(workspace_id, id)` means the same
upstream `user_id` (e.g. an Auth0 `sub`) can coexist as two
independent principals in two workspaces.

### Reserved ids

`"system"` is rejected by `create` — it is the sentinel for the
disabled-RBAC `User.system()` fallback. Persisting it would shadow
the fallback identity and confuse audit trails.

---

## Migrations

Postgres ships migration `0003_rbac.py` (depends on
`0002_tenancy_columns`). It creates:

* `users (workspace_id, id, organization_id, display_name, created_at)`
* `user_roles (workspace_id, user_id, role, organization_id,
  created_at)` with FK → `users(workspace_id, id) ON DELETE CASCADE`
* Indexes `ix_users_workspace`, `ix_user_roles_user`,
  `ix_user_roles_role`

The migration is idempotent (`CREATE TABLE IF NOT EXISTS` /
`CREATE INDEX IF NOT EXISTS`). Downgrade drops the two tables CASCADE
and reverts to revision `0002_tenancy_columns`. The full chain
`0001 → 0002 → 0003 ← 0002 ← base` is exercised by
`adapters/postgres-store/tests/test_migrations.py`.

SQLite has no dedicated migration — `SQLiteStore.initialize()` runs
`Base.metadata.create_all()` and picks up the new tables
automatically.

---

## Integration patterns

### Pattern 1: gateway injects headers (recommended)

Production deployments put Wake behind a gateway (nginx, Envoy,
Traefik, API Gateway) that does the IdP handshake and injects the
three headers Wake consumes:

```
Client → IdP → Gateway → Wake
                  │
                  └── adds X-Wake-Organization-Id
                  └── adds X-Wake-Workspace-Id
                  └── adds X-Wake-User-Id
                  └── adds X-Wake-API-Key  (machine-machine)
```

The gateway is the only thing trusted with the IdP secret. Wake never
sees raw tokens, and rotating IdPs is a gateway-config change.

### Pattern 2: API key per user (small deployments)

For internal tools where every operator already authenticates to Wake
via an API key, the gateway can map each key to a `X-Wake-User-Id`
using a static table. Each role is bound to the user once via
`POST /v1/users/{id}/roles`. This trades flexibility for simplicity:
losing a key requires revoking the user.

### Pattern 3: dashboard SSO

The Wake Dashboard (Next.js front-end) accepts a session cookie from
the operator's SSO provider and forwards the matching `user_id` on
every API call. The dashboard sees `roles[]` from `/v1/users/me`
and renders read-only / write-allowed UI accordingly.

---

## Audit and observability

Wake does not yet emit `user.action` events into the event log —
that's a Phase 7 line item (gap #4: structured admin trail). What
ships today:

* Every gated route returns 403 with a `forbidden: requires one of
  admin, operator` body so reverse proxies / WAFs can log and rate-
  limit denied attempts.
* The `users.created` log line (structlog) carries `user_id` +
  `workspace_id`. SQLite/Postgres stores write at INFO level.
* `GET /v1/vault/audit` continues to log every credential operation
  with the caller's identity — this was added in Phase 5 and is
  unchanged.

Until the structured admin trail lands, operators should pipe
structlog through their log shipper (DataDog / Honeycomb / Loki /
ELK) and alert on 403/401 spikes.

---

## Threat model

In-scope:

* **Cross-tenant isolation.** A workspace_a admin cannot read /
  write workspace_b resources — guaranteed by the tenancy layer
  (404 on every cross-workspace lookup). RBAC adds the second
  layer: even within a workspace, a viewer cannot mutate.
* **Privilege drift.** Roles are explicit and per-route. Adding a
  new write endpoint that forgets the decorator falls open. Mitigated
  by the per-route enforcement matrix in
  `tests/unit/test_api_rbac_enforcement.py` — adding a new route
  without updating the test is a CI failure.
* **Reserved-id smuggling.** Persisting a row with `id = "system"`
  would let an attacker masquerade as the disabled-RBAC fallback.
  Rejected by both `SQLiteUserStore.create` and
  `PostgresUserStore.create`.

Out-of-scope (Wake trusts the gateway):

* **Header forgery.** Anyone able to inject `X-Wake-User-Id` directly
  bypasses the IdP. Wake assumes the gateway strips inbound copies
  of the header from external traffic. This is the deal-breaker for
  exposing Wake directly to the public internet without a gateway.
* **User-password storage.** Wake never stores passwords. Anyone
  needing local password auth must front Wake with a gateway that
  carries a password DB (Dex, Authentik, custom).

---

## Operational runbook

### Turning RBAC on for the first time

1. Wire a `UserStore` in `create_app(user_store=...)` (or
   `wake.api.bootstrap`).
2. Run the Postgres migration (`alembic upgrade head`) — SQLite is
   automatic.
3. Pre-seed at least one admin user **before** flipping the env var:

   ```bash
   curl -X POST /v1/users \
        -H 'X-Wake-API-Key: ...' \
        -H 'X-Wake-Workspace-Id: default' \
        -d '{"id": "bootstrap-admin", "roles": ["admin"]}'
   ```

   With RBAC still off the `system` user can issue this call.

4. Set `WAKE_RBAC_ENABLED=true` in the deployment.
5. Restart the API replicas (or roll the deployment).
6. Verify a fresh login via `/v1/users/me` returns the seed admin.

### Recovering from a locked-out workspace

Symptom: every admin user was accidentally deleted / had their role
revoked. RBAC gates lock you out of `/v1/users` writes.

Recovery:

1. Set `WAKE_RBAC_ENABLED=false` on at least one replica.
2. Hit `POST /v1/users` or `POST /v1/users/{id}/roles` with no
   user header — runs as `system` (full admin).
3. Re-enable RBAC and roll the cluster.

This is the deliberate "break-glass" path. We do **not** ship a CLI
that bypasses the API on purpose: operator-side scripts that talk
directly to the Postgres / SQLite DB are the recommended audit hop
when even the break-glass path is unavailable (lost env access).

### Rolling RBAC out per workspace

If you want to enable RBAC for one workspace while keeping others in
back-compat mode, deploy two API replica sets with different
`WAKE_RBAC_ENABLED` values, fronted by a router that pins traffic
by workspace. The simpler path is to flip everyone at once after
seeding all admins.

---

## Limitations and what is NOT shipped

* **No custom roles.** Adding `BILLING` or `AUDITOR` requires a
  code change. Phase 7 will introduce a `roles` table with operator-
  defined entries.
* **No row-level scoping.** A workspace admin can do everything in
  the workspace. There is no "this admin can only manage these
  agents" tier.
* **No password store.** Authentication is delegated to the gateway.
* **No OAuth login for end-users.** The vault already supports
  third-party OAuth, but that's for *Wake to read upstream
  credentials*, not for *users to log into Wake*.
* **No event-trail of admin actions.** A `user.action` event type
  is on the roadmap but not in Phase 6.
* **No service-to-service principal type.** Every call is "either
  the system user (RBAC off) or a real user (RBAC on)". Machine
  callers reuse a user identity by convention.

---

## Future work

* **Phase 7 — admin trail:** emit `user.action` events for every
  write, with `user_id`, `route`, `payload_summary`, `decision`.
* **Phase 7 — custom roles:** operator-defined role names with a
  serialised permission set, replacing the hard-coded enum.
* **Phase 7 — row-level policies:** binding a role to a specific
  resource subset (`alice can only manage agents tagged team_a`).
* **Phase 7 — short-lived tokens:** trade `X-Wake-API-Key` for a
  signed token carrying `user_id` + `workspace_id`, removing the
  header-forge risk surface.

References:

* `phases/PHASE-6-CONTRACT.md` — original spec.
* `src/wake/rbac.py` — role + user dataclass + flag helper.
* `src/wake/api/dependencies.py` — `get_current_user`,
  `require_role`.
* `src/wake/api/routes/users.py` — CRUD endpoints.
* `tests/unit/test_rbac.py`, `test_api_users.py`,
  `test_api_rbac_enforcement.py` — behavioural coverage.
* `adapters/postgres-store/alembic/versions/0003_rbac.py` —
  migration.
