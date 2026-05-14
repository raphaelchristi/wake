# Wake — Operational Runbook

> Phase 6 / Tier 0 gaps #1 + #2 + #3.
> Owner: tenancy-ops slice + on-call rotation.
> Last reviewed: 2026-05-14.

This runbook is your **page-and-act companion** for the four highest-
severity Wake incidents. Each playbook is structured the same way:

1. **Symptoms** — how you know you're in it
2. **Severity + impact** — who's affected
3. **Pre-flight** — what to check before acting
4. **Containment** — stop the bleeding (priority 1)
5. **Investigation** — find root cause (priority 2)
6. **Remediation** — fix it
7. **Validation** — confirm the fix
8. **Post-mortem inputs** — what to capture

For backup-specific procedures (restore from scratch, drill, troubleshooting
S3 errors) see [`DISASTER-RECOVERY.md`](DISASTER-RECOVERY.md).

---

## Table of contents

- [Playbook 1: Tenant data isolation breach](#playbook-1-tenant-data-isolation-breach)
- [Playbook 2: Backup + restore from scratch](#playbook-2-backup--restore-from-scratch)
- [Playbook 3: RBAC bypass detection](#playbook-3-rbac-bypass-detection)
- [Playbook 4: Cross-workspace event leakage](#playbook-4-cross-workspace-event-leakage)
- [Appendix: useful queries + commands](#appendix-useful-queries--commands)

---

## Playbook 1: Tenant data isolation breach

> **Severity**: P0 (security incident — data exposure across tenants)
> **SLO**: contain < 30min, investigate < 4h, remediate < 24h

### Symptoms

One or more of:

- User in `org-A/workspace-X` reports seeing data (a session, an event,
  a credential) belonging to `org-B/workspace-Y`
- Audit log shows a `GET /v1/sessions/{id}` returning 200 when the
  caller's `X-Wake-Workspace-Id` didn't match the row's `workspace_id`
- Application logs include `tenant_mismatch` events for production
  traffic (not just tests)
- Internal red-team / pen-test report

### Severity + impact

A **single confirmed breach is P0**. Reasons:

- Multi-tenant safety is Wake's core contract (Phase 6 Tier 0 gap #1).
  If isolation breaks, every customer must be notified.
- Even if only metadata leaked (not events), the *existence* of another
  tenant's sessions counts as a leak.

If the breach is **read-only metadata** (e.g. a count, not the rows
themselves) it stays P0 but the regulatory clock is more forgiving.

### Pre-flight

- [ ] **Capture evidence**: screenshot the API response, save the exact
      request headers (`X-Wake-Organization-Id`, `X-Wake-Workspace-Id`,
      `X-Wake-User-Id` if RBAC on), the response body, and the timestamp.
- [ ] **Confirm it's reproducible** with a controlled test against
      staging — *before* taking down prod. Often a "breach" is a stale
      cache after the user switched workspaces. Run:
      ```bash
      curl -H "X-Wake-API-Key: $KEY" \
           -H "X-Wake-Organization-Id: org-A" \
           -H "X-Wake-Workspace-Id: workspace-X" \
           https://api.wake.example.com/v1/sessions/<the-other-tenants-session-id>
      ```
      Expected: 404 (Phase 6 decision: cross-workspace returns 404, not
      403, to avoid existence-leakage).
- [ ] **Determine blast radius**: how long has this been possible? Look
      for a recent deploy that changed:
      - `src/wake/tenancy.py`
      - `src/wake/api/dependencies.py` (`get_tenant_context`)
      - Any route under `src/wake/api/routes/` that takes a `session_id`
      - Postgres migrations touching `organization_id` / `workspace_id`
      - `frontend/src/lib/api/client.ts` (tenant header injection)

### Containment

**Priority 1 — stop further data exposure.**

If breach is **read-only via a specific endpoint**:

```bash
# Block the offending route at the ingress layer.
# Example: nginx-ingress with a snippet.
kubectl -n wake annotate ingress wake \
  nginx.ingress.kubernetes.io/configuration-snippet='
    location ~ ^/v1/sessions/[^/]+$ {
      return 503;
    }
  ' --overwrite
```

If breach affects **all reads from a specific endpoint family** (e.g.
all `/v1/sessions`):

```bash
# Scale API to 0 — total outage; only do this if the alternative is
# uncontrolled data exposure to other tenants.
kubectl -n wake scale deploy wake-api --replicas=0
```

If breach is **write-side** (one tenant's writes landed in another's
rows): emergency stop everything.

```bash
kubectl -n wake scale deploy wake-api wake-worker --replicas=0
```

**Notify**:
- Incident channel
- Affected customer (after legal review if scoped to enterprise)
- Status page

### Investigation

Look at the **3 layers** of isolation:

#### Layer 1 — header parsing (`src/wake/tenancy.py`)

```bash
kubectl -n wake exec -it deploy/wake-api -- \
  python -c "from wake.tenancy import TenantContext; \
             print(TenantContext.from_headers({'x-wake-organization-id': 'foo', 'x-wake-workspace-id': 'bar'}))"
```

Expected: `TenantContext(organization_id='foo', workspace_id='bar')`.
If empty/default fallback is happening when the headers ARE present,
that's the bug.

#### Layer 2 — query scoping (stores)

For each affected entity (`sessions`, `events`, `agents`, etc), grep:

```bash
# In a checkout of the source repo:
rg "workspace_id" src/wake/store/sqlite.py
rg "workspace_id" adapters/postgres-store/src/wake_store_postgres/
```

Every SELECT/UPDATE/DELETE against a tenanted table MUST include a
`WHERE workspace_id = ?` predicate. If you find a query that doesn't,
that's the bug.

#### Layer 3 — response shape

Even if scoping is correct, double-check that error paths don't leak.
For instance, an unscoped `404` page that includes `<title>Session abc
not found in workspace def</title>` would leak existence. Test:

```bash
curl -i -H "X-Wake-API-Key: $KEY" \
     -H "X-Wake-Organization-Id: random-tenant" \
     -H "X-Wake-Workspace-Id: random-workspace" \
     https://api.wake.example.com/v1/sessions/<known-session-id>
# Expected: 404 with NO body details about which tenant the session belongs to.
```

#### Audit query

Find all cross-workspace reads in the last 7 days:

```sql
-- Run against Postgres (read replica recommended).
SELECT
  request_id,
  caller_org,
  caller_workspace,
  target_workspace,
  endpoint,
  response_code,
  ts
FROM audit_log
WHERE caller_workspace <> target_workspace
  AND response_code = 200
  AND ts > NOW() - INTERVAL '7 days'
ORDER BY ts DESC
LIMIT 500;
```

(If the audit log doesn't have these columns yet — capture this as a
post-mortem follow-up; add structured audit logging in Phase 7.)

### Remediation

#### Hotfix path

1. **Branch from the latest tag**:
   ```bash
   git checkout -b hotfix/phase6-tenant-isolation v0.6.0-tenancy
   ```
2. **Add a regression test** that exercises the exact breach scenario.
   Tests live in `tests/unit/test_api_tenancy.py`. The test must fail
   on `main` *before* the fix is applied.
3. **Patch the offending code path**. Common shapes:
   - Forgotten `WHERE workspace_id = ?` → add the predicate
   - `get_tenant_context` returning `default/default` when headers
     present → fix the parser
   - Frontend not injecting `X-Wake-Workspace-Id` for one specific hook
     → patch `frontend/src/hooks/<the-hook>.ts`
4. **Build + push** image, bump chart `image.tag`:
   ```bash
   docker build -f deploy/Dockerfile -t wake-ai/wake:0.6.1-hotfix .
   docker push wake-ai/wake:0.6.1-hotfix
   ```
5. **Roll the fix**:
   ```bash
   helm upgrade wake ./deploy/helm/wake --reuse-values \
     --set image.tag=0.6.1-hotfix
   ```

#### Re-enable traffic

After verifying the fix in staging:

```bash
# Remove the ingress block (if applied).
kubectl -n wake annotate ingress wake \
  nginx.ingress.kubernetes.io/configuration-snippet- --overwrite

# Scale back up.
kubectl -n wake scale deploy wake-api wake-worker --replicas=2
```

### Validation

- [ ] Manual repro of the original breach: now returns 404 (or 403 if
      RBAC-related)
- [ ] All tests in `tests/unit/test_api_tenancy.py` pass
- [ ] The new regression test fails on `v0.6.0-tenancy` and passes on
      the hotfix
- [ ] Audit log for the past 10 minutes shows zero `tenant_mismatch`
      events from production traffic
- [ ] Affected customer reports the issue is gone

### Post-mortem inputs

- Detection lag (when did breach start vs when was it reported?)
- Containment lag (incident reported → traffic stopped)
- Root cause class: `missing-where-clause` | `bad-header-parse` |
  `cache-not-cleared` | `frontend-fixture-fallback` | other
- Why didn't tests catch it? (specific test gap to add)
- Action items: more tenant-mismatch alerting? Stricter mypy on store
  query helpers?

---

## Playbook 2: Backup + restore from scratch

> **Severity**: P0 if data is unrecoverable; P1 if PG is degraded but live
> **SLO**: restore complete < 30min (RTO budget)

### Symptoms

One or more of:

- `wake-postgres-0` is in `CrashLoopBackOff` and the underlying disk
  has filesystem errors visible in `dmesg` / kernel logs
- PVC was accidentally deleted (operator error, terraform misapply)
- Production data was corrupted by a bad migration / rogue
  `DELETE FROM events WHERE ...` / ransomware encryption
- DR drill (planned exercise)
- Cluster lost — restoring in a new region/cluster from S3 backup only

### Severity + impact

- **Data unrecoverable from PVC → P0**. All Wake traffic stops until
  Postgres comes back online.
- **PVC is fine, just doing a planned PITR → P1**. Plan a maintenance
  window.

### Pre-flight

- [ ] Confirm S3 bucket is reachable and contains recent backups:
      ```bash
      aws s3 ls s3://wake-backups-prod/pgbackrest/backup/wake-wake/ | tail -10
      ```
- [ ] Decide WHICH backup to restore. Latest is usually right. For
      data-corruption scenarios, restore the backup *immediately before*
      the corruption window started. Use `pgbackrest info` to enumerate:
      ```bash
      kubectl -n wake create job --from=cronjob/wake-backup-full \
        wake-info-$(date +%s) -- pgbackrest --stanza=wake-wake info
      ```
- [ ] Snapshot the existing PVC if recoverable (gives you a fallback if
      restore goes wrong):
      ```bash
      # AWS EBS example
      VOLUME_ID=$(kubectl -n wake get pvc data-wake-postgres-0 -o jsonpath='{.spec.volumeName}' \
                  | xargs kubectl get pv -o jsonpath='{.spec.awsElasticBlockStore.volumeID}')
      aws ec2 create-snapshot --volume-id "$VOLUME_ID" \
        --description "wake-postgres-pre-restore-$(date +%s)"
      ```
- [ ] Open incident channel; post status page banner ("Wake API
      maintenance window 15-30min").
- [ ] Note the start timestamp — RTO clock begins now.

### Containment

```bash
# 1. Stop writers — API + workers.
kubectl -n wake scale deploy wake-api wake-worker --replicas=0

# 2. Wait for pods to terminate.
kubectl -n wake wait --for=delete pod -l app.kubernetes.io/component=api --timeout=2m
kubectl -n wake wait --for=delete pod -l app.kubernetes.io/component=worker --timeout=2m

# 3. Stop Postgres.
kubectl -n wake scale statefulset wake-postgres --replicas=0
kubectl -n wake wait --for=delete pod/wake-postgres-0 --timeout=2m
```

### Restoration

Follow [`DISASTER-RECOVERY.md` § Restore procedure](DISASTER-RECOVERY.md#restore-procedure-step-by-step)
verbatim. Summary:

```bash
# 1. Launch a restore pod that mounts the postgres PVC.
kubectl -n wake apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: wake-postgres-restore
spec:
  restartPolicy: Never
  serviceAccountName: wake-backup
  containers:
    - name: pgbackrest
      image: pgbackrest/pgbackrest:2.54.0
      command: ["/bin/bash","-c","pgbackrest --stanza=wake-wake --pg1-path=/var/lib/postgresql/data --delta restore && chown -R 999:999 /var/lib/postgresql/data && sleep 60"]
      env:
        - {name: PGBACKREST_REPO1_S3_KEY,        valueFrom: {secretKeyRef: {name: wake-backup-s3-creds, key: access-key-id}}}
        - {name: PGBACKREST_REPO1_S3_KEY_SECRET, valueFrom: {secretKeyRef: {name: wake-backup-s3-creds, key: secret-access-key}}}
      volumeMounts:
        - {name: pgbackrest-config, mountPath: /etc/pgbackrest, readOnly: true}
        - {name: pgdata, mountPath: /var/lib/postgresql/data}
  volumes:
    - {name: pgbackrest-config, configMap: {name: wake-wake-pgbackrest}}
    - {name: pgdata, persistentVolumeClaim: {claimName: data-wake-postgres-0}}
EOF

# 2. Watch the restore.
kubectl -n wake logs -f wake-postgres-restore

# 3. After "restore complete", clean up the restore pod and bring PG up.
kubectl -n wake delete pod wake-postgres-restore
kubectl -n wake scale statefulset wake-postgres --replicas=1
kubectl -n wake wait --for=condition=ready pod/wake-postgres-0 --timeout=3m

# 4. Verify row counts.
kubectl -n wake exec -it wake-postgres-0 -- psql -U wake -d wake -c "
  SELECT 'agents' AS table_name, COUNT(*) FROM agents
  UNION ALL SELECT 'environments', COUNT(*) FROM environments
  UNION ALL SELECT 'sessions', COUNT(*) FROM sessions
  UNION ALL SELECT 'events', COUNT(*) FROM events;
"

# 5. Bring API + workers back.
kubectl -n wake scale deploy wake-api wake-worker --replicas=2
kubectl -n wake wait --for=condition=available deploy/wake-api --timeout=2m

# 6. Smoke check.
curl -fH "X-Wake-API-Key: $WAKE_API_KEY" https://api.wake.example.com/health

# 7. Trigger a fresh full backup to baseline the future chain.
kubectl -n wake create job --from=cronjob/wake-backup-full \
  wake-backup-post-restore-$(date +%s)
```

### Validation

- [ ] `pg_isready` returns 0 in the postgres pod
- [ ] `kubectl -n wake exec wake-postgres-0 -- psql -U wake -d wake -c "\dt"` lists expected tables
- [ ] Row counts on `sessions`, `events`, `agents`, `environments` are
      within ~5% of last known good (compare to pre-disaster Grafana export)
- [ ] `curl /health` returns `{"status":"ok"}`
- [ ] A canary user can log into the dashboard and see their workspace
- [ ] Post-restore backup job ran successfully (`pgbackrest info` shows
      a new `F` entry with today's timestamp)
- [ ] Wall-clock RTO ≤ 30min

### Post-mortem inputs

- Actual RTO vs budget
- Actual RPO (timestamp of MAX(created_at) on `events` after restore)
- Which backup was used (full vs incremental, label, age)
- Anything that didn't go per runbook — file Phase 7 tickets
- Update drill log template entry

---

## Playbook 3: RBAC bypass detection

> **Severity**: P0 (privilege escalation)
> **SLO**: contain < 30min, investigate < 4h, remediate < 24h
> **Prereq**: RBAC must be enabled (`WAKE_RBAC_ENABLED=true`) for this
> playbook to apply. If RBAC is off (the default in Phase 6), every
> caller is treated as `System` — this playbook reduces to Playbook 1.

### Symptoms

One or more of:

- A `viewer`-roled user successfully created/modified/deleted a session,
  agent, environment, or credential
- An `operator`-roled user successfully modified a user role or vault credential
- Audit log shows `403 → 200` transitions on the same `(user, route)`
  pair without a role-change event in between
- `X-Wake-User-Id` was forged or omitted and the API treated the caller
  as admin
- A user reports "I can see things I shouldn't"

### Severity + impact

- Privilege escalation → P0
- Could be combined with Playbook 1 (tenant isolation breach) if the
  escalated role gives cross-tenant access

### Pre-flight

- [ ] **Capture the bypass evidence**: exact request headers, method, URL,
      response code, response body, server timestamp
- [ ] **Identify the bypassed gate**: which `require_role(...)` call
      should have blocked this? Run:
      ```bash
      grep -r "require_role" src/wake/api/routes/
      ```
- [ ] **Confirm RBAC is enabled**:
      ```bash
      kubectl -n wake exec deploy/wake-api -- env | grep WAKE_RBAC_ENABLED
      # Expected: WAKE_RBAC_ENABLED=true
      # If false → not a bypass, RBAC is just off. Different playbook.
      ```

### Containment

If the bypassed user/role combo is widely exposed:

```bash
# 1. Switch RBAC enforcement to a more conservative mode by flipping
#    the env var to a stricter setting (if available) or rolling back
#    to the last known-good image tag.
helm upgrade wake ./deploy/helm/wake --reuse-values \
  --set image.tag=0.6.0-tenancy  # known-good baseline

# 2. If the bypass is specific to one endpoint, block at the ingress
#    until the patch ships.
kubectl -n wake annotate ingress wake \
  nginx.ingress.kubernetes.io/configuration-snippet='
    location ~ ^/v1/users/.*/roles {
      return 503;
    }
  ' --overwrite

# 3. Revoke any obviously-malicious roles assigned during the bypass
#    window:
kubectl -n wake exec deploy/wake-api -- python -c "
from wake.store.factory import build_user_store_from_env
from wake.rbac import Role
import asyncio

async def main():
    store = await build_user_store_from_env()
    await store.revoke_role(user_id='<suspect-user>', role=Role.ADMIN, workspace_id='<workspace>')
asyncio.run(main())
"
```

### Investigation

#### Verify the gate exists

For every write-y endpoint, the route function signature should be:

```python
async def create_session(
    payload: SessionCreate,
    user: Annotated[User, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
    ...
):
```

Grep for endpoints that ARE supposed to enforce a role but don't:

```bash
# Routes that should have a require_role gate.
rg "^(async )?def (create|update|delete|patch|archive|interrupt)" src/wake/api/routes/ -B 5 \
  | rg -B 5 "def (create|update|delete|patch|archive|interrupt)" \
  | grep -v "require_role"
```

Any hit is a candidate bug.

#### Check user-role binding integrity

```sql
SELECT u.id, u.display_name, ur.role, ur.workspace_id, ur.created_at
FROM users u
JOIN user_roles ur ON ur.user_id = u.id
WHERE u.id = '<suspect-user-id>'
ORDER BY ur.created_at DESC;
```

Looking for roles that were assigned without an admin actor on record.

#### Check `X-Wake-User-Id` injection chain

The user header is intended to be injected by a trusted gateway/IdP.
If your deployment lets clients set it directly, the bypass is trivial.

```bash
# 1. Is there an OAuth proxy / API gateway in front?
kubectl -n wake describe ingress wake | grep -i auth

# 2. If yes, verify it strips client-provided X-Wake-User-Id and
#    re-injects after auth.
```

### Remediation

Patch shape depends on root cause:

| Root cause | Patch |
|---|---|
| Forgotten `require_role(...)` on a route | Add the dependency; ship hotfix |
| `require_role` checks against tenant-scoped roles but role lookup uses default tenant | Fix the lookup to use the same tenant context |
| Trusted-header injection (client sets `X-Wake-User-Id`) | Add ingress / gateway rule to strip + re-inject |
| Role assignment with no admin actor logged | Audit-log all role mutations + add a check in `assign_role` |

Add a regression test in `tests/unit/test_api_rbac_enforcement.py`:

```python
async def test_viewer_cannot_create_session(client, viewer_token):
    response = await client.post(
        "/v1/sessions",
        json={...},
        headers={"X-Wake-User-Id": "viewer-user", "X-Wake-API-Key": "..."},
    )
    assert response.status_code == 403  # was returning 200 in the breach
```

Ship the hotfix:

```bash
helm upgrade wake ./deploy/helm/wake --reuse-values \
  --set image.tag=0.6.1-hotfix
```

### Validation

- [ ] Replay the bypass: now returns 403
- [ ] Regression test passes locally + in CI
- [ ] Audit log for last hour shows zero `unauthorized-success` events
      (where status=200 but role check should have failed)
- [ ] Suspect user accounts: their roles are either correct or revoked

### Post-mortem inputs

- Was the bypass exploited or just theoretically possible?
- How long did the gap exist? (compare timestamps of route change vs
  hotfix)
- Why didn't `test_api_rbac_enforcement.py` catch it? (missing matrix
  cell)
- Should the role matrix be denormalized into a Pydantic config so
  drift is impossible? (Phase 7 ticket)

---

## Playbook 4: Cross-workspace event leakage

> **Severity**: P0 (subset of Playbook 1 — but specific to the event
> stream, which is real-time and harder to revoke)
> **SLO**: contain < 30min (stop the SSE leak), investigate < 4h

### Symptoms

One or more of:

- User in `workspace-X` opened a session detail page and SSE events
  for sessions in `workspace-Y` started flowing in
- Frontend dev tools: `EventSource` URL contains another tenant's
  `workspace_id` query parameter
- Audit log shows `GET /v1/sessions/{id}/stream` returning 200 when
  the session belongs to a different workspace
- Replay viewer renders events with mismatched `workspace_id` field

### Severity + impact

- Real-time event leakage = P0
- Events may contain tool inputs, model outputs, vault metadata —
  potentially highly sensitive
- Because SSE is long-lived, even a brief misconfiguration can leak
  thousands of events per minute

### Pre-flight

- [ ] **Capture an example malicious SSE session**:
      ```bash
      curl -N -H "X-Wake-API-Key: $KEY" \
           "https://api.wake.example.com/v1/sessions/<other-tenants-session>/stream?org=tenant-A&ws=workspace-X"
      ```
      If events stream → confirmed leak.
- [ ] **Identify which transport layer broke**: backend route, Next.js
      proxy, or query-string parsing.

### Containment

```bash
# 1. Block the SSE endpoint at ingress immediately.
kubectl -n wake annotate ingress wake \
  nginx.ingress.kubernetes.io/configuration-snippet='
    location ~ ^/v1/sessions/[^/]+/stream {
      return 503;
    }
  ' --overwrite

# 2. Force-disconnect any in-flight SSE clients by rolling the API.
kubectl -n wake rollout restart deploy/wake-api

# (The frontend will see the SSE connection drop and back off
# automatically. Users will see "reconnecting..." until the fix ships.)
```

### Investigation

#### Layer A — backend SSE route

`src/wake/api/routes/sessions.py` (or wherever `/v1/sessions/{id}/stream`
is defined) MUST:

1. Read `session_id` from the path
2. Read `org` + `ws` from the query string (per Phase 6 decision —
   SSE uses query string not header because `EventSource` can't set
   custom headers)
3. **Re-validate** that the session at `session_id` actually belongs to
   the `(org, ws)` claimed in the query string
4. If mismatch → 404 (not 403)

```bash
# Find the route handler.
rg "def.*stream" src/wake/api/routes/sessions.py

# Verify it calls something equivalent to:
#   if session.workspace_id != ctx.workspace_id: raise HTTPException(404)
```

If the check is missing → that's the bug.

#### Layer B — Next.js proxy route

`frontend/src/app/api/wake/sessions/[id]/stream/route.ts` MUST:

1. Sanitize `org` + `ws` query params against the regex
   `^[a-z0-9][a-z0-9_-]{0,62}$` (per Phase 6 decision — prevents
   header injection via query string)
2. Reject with 400 if either fails the regex
3. Forward to backend with `X-Wake-Organization-Id` + `X-Wake-Workspace-Id`
   headers set from the (sanitized) query params

If a malicious `ws=workspace-A%0AX-Wake-Workspace-Id:%20workspace-B`
went through unsanitized → critical bug.

```bash
# Inspect the proxy code.
cat frontend/src/app/api/wake/sessions/[id]/stream/route.ts
```

#### Layer C — frontend hook

`frontend/src/hooks/useSSE.ts` MUST carry `workspaceId` into the
URL it passes to `EventSource`. If the hook reads `workspaceId` from
a stale closure (e.g. captured at mount instead of via current state),
it may emit a URL with the wrong workspace.

```bash
# Verify the hook uses the workspace from the current TanStack Query
# key / context, not a stale prop.
rg "EventSource" frontend/src/hooks/useSSE.ts
```

#### Audit query

```sql
-- Find SSE requests where the workspace_id in the request didn't
-- match the session's actual workspace_id.
SELECT
  request_id,
  ts,
  caller_workspace,
  session_id,
  target_workspace
FROM audit_log
WHERE endpoint LIKE '/v1/sessions/%/stream'
  AND caller_workspace <> target_workspace
  AND response_code = 200
ORDER BY ts DESC;
```

### Remediation

Patch shape:

| Root cause | Patch |
|---|---|
| Backend SSE route missing workspace check | Add `if session.workspace_id != ctx.workspace_id: raise HTTPException(404)` |
| Next.js proxy doesn't sanitize | Add regex check; 400 on mismatch |
| Frontend hook captures stale workspace | Move workspace into the `EventSource` URL via current state |

Add tests:

- Backend: `tests/unit/test_api_tenancy.py::test_stream_rejects_cross_workspace`
- Frontend: `frontend/tests/unit/sse-proxy.test.ts::rejects bad chars`
- E2E: `frontend/tests/e2e/multi-workspace.spec.ts::SSE isolation`

Ship hotfix:

```bash
helm upgrade wake ./deploy/helm/wake --reuse-values \
  --set image.tag=0.6.1-hotfix
```

### Validation

- [ ] Re-run the original cross-workspace SSE attempt — now returns
      404 (or 400 if proxy rejected)
- [ ] Open the dashboard, switch workspaces — confirm SSE stream
      reconnects with the new workspace ID and shows only that
      workspace's events
- [ ] Audit log for last hour shows zero cross-workspace 200s on
      `/v1/sessions/{id}/stream`
- [ ] Reactor/replay viewer shows no events with mismatched workspace_id
- [ ] Unblock ingress:
      ```bash
      kubectl -n wake annotate ingress wake \
        nginx.ingress.kubernetes.io/configuration-snippet- --overwrite
      ```

### Post-mortem inputs

- Number of cross-workspace event records that flowed during the gap
- Customer list affected
- Why didn't multi-workspace e2e tests catch it? (specific test gap)
- Should we add a per-event invariant check (event's workspace_id ==
  session's workspace_id) at write time? (Phase 7)

---

## Appendix: useful queries + commands

### Audit log queries

> Note: these queries assume an `audit_log` table exists. Phase 6 ships
> with the **schema** (workspace_id columns in sessions/agents/events)
> but the audit log itself is a Phase 7 deliverable. Capture audit data
> from application logs for now.

```sql
-- Top 10 cross-workspace request attempts (any status).
SELECT caller_workspace, target_workspace, COUNT(*)
FROM audit_log
WHERE caller_workspace <> target_workspace
  AND ts > NOW() - INTERVAL '24 hours'
GROUP BY caller_workspace, target_workspace
ORDER BY COUNT(*) DESC
LIMIT 10;

-- All write operations by viewer-role users (should be zero).
SELECT u.id, u.display_name, a.endpoint, a.method, a.ts
FROM audit_log a
JOIN user_roles ur ON ur.user_id = a.user_id
JOIN users u ON u.id = a.user_id
WHERE ur.role = 'viewer'
  AND a.method IN ('POST', 'PATCH', 'DELETE')
  AND a.response_code < 400
ORDER BY a.ts DESC
LIMIT 100;

-- Recent 503 responses (containment ingress block hits).
SELECT endpoint, COUNT(*) AS hits
FROM audit_log
WHERE response_code = 503
  AND ts > NOW() - INTERVAL '1 hour'
GROUP BY endpoint
ORDER BY hits DESC;
```

### Useful kubectl one-liners

```bash
# All resources for a release.
kubectl -n wake get all -l app.kubernetes.io/instance=wake

# Last 5 events in the namespace (catching scheduler problems).
kubectl -n wake get events --sort-by=.lastTimestamp | tail -20

# Tail logs for one component.
kubectl -n wake logs -l app.kubernetes.io/component=api --tail=100 -f

# Exec into the API.
kubectl -n wake exec -it deploy/wake-api -- /bin/sh

# Check CronJob status.
kubectl -n wake get cronjob -l app.kubernetes.io/component=backup -o wide

# Manually trigger a CronJob.
kubectl -n wake create job --from=cronjob/wake-backup-full wake-manual-$(date +%s)

# Suspend a CronJob (e.g. during incident).
kubectl -n wake patch cronjob wake-backup-full -p '{"spec":{"suspend":true}}'

# Force-delete a stuck pod (LAST RESORT).
kubectl -n wake delete pod <pod> --force --grace-period=0
```

### Useful psql one-liners

```bash
# Open a psql shell.
kubectl -n wake exec -it wake-postgres-0 -- psql -U wake -d wake

# Quick row counts.
kubectl -n wake exec -it wake-postgres-0 -- psql -U wake -d wake -c "
  SELECT relname, n_live_tup
  FROM pg_stat_user_tables
  ORDER BY n_live_tup DESC LIMIT 20;
"

# Active connections (look for stuck transactions).
kubectl -n wake exec -it wake-postgres-0 -- psql -U wake -d wake -c "
  SELECT pid, usename, application_name, state, query_start, wait_event_type, wait_event
  FROM pg_stat_activity
  WHERE state != 'idle'
  ORDER BY query_start;
"

# Long-running queries (> 1 minute).
kubectl -n wake exec -it wake-postgres-0 -- psql -U wake -d wake -c "
  SELECT pid, NOW() - query_start AS duration, state, query
  FROM pg_stat_activity
  WHERE state != 'idle' AND NOW() - query_start > INTERVAL '1 minute'
  ORDER BY duration DESC;
"

# Check WAL archive status (if archiving enabled).
kubectl -n wake exec -it wake-postgres-0 -- psql -U wake -d wake -c "
  SELECT * FROM pg_stat_archiver;
"
```

### Useful pgbackrest one-liners

```bash
# Backup inventory.
kubectl -n wake create job --from=cronjob/wake-backup-full \
  wake-info-$(date +%s) -- pgbackrest --stanza=wake-wake info

# Verify repository integrity.
kubectl -n wake create job --from=cronjob/wake-backup-full \
  wake-check-$(date +%s) -- pgbackrest --stanza=wake-wake check

# Force a full backup (off-schedule).
kubectl -n wake create job --from=cronjob/wake-backup-full \
  wake-force-full-$(date +%s)

# Force an incremental.
kubectl -n wake create job --from=cronjob/wake-backup-incremental \
  wake-force-incr-$(date +%s)
```

### Incident timeline template

Copy into your incident channel.

```
INCIDENT YYYY-MM-DD-NN — <one-line description>

Status: [INVESTIGATING | CONTAINED | RESOLVED]
Severity: [P0 | P1 | P2]
Started: <UTC timestamp>
Detected by: <alert / human report / drill>
On-call: <name>
Comms: <name>

Timeline:
  T+0:00  <ISO timestamp>  detection
  T+0:05                  containment action
  T+0:NN                  investigation finding X
  T+0:NN                  remediation deployed
  T+0:NN                  validation complete
  T+0:NN                  RESOLVED

Customers affected: <list or "none confirmed">
Data exposed: <yes / no — details>
Root cause: <one sentence>
Next steps: <links to follow-up tickets>
```

---

## Sign-off

This runbook is reviewed:

- **Monthly** during ops review
- **After any incident** that exercises it (update with lessons learned)
- **Before each minor Wake release** if tenancy / RBAC / backup paths changed

Owner of last review: tenancy-ops slice, Phase 6 — 2026-05-14.
