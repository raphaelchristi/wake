# Disaster Recovery — Wake

> Phase 6 / Tier 0 gap #3.
> Owner: tenancy-ops slice.
> Last reviewed: 2026-05-14.

---

## Table of contents

1. [Executive summary](#executive-summary)
2. [Recovery targets (RTO / RPO)](#recovery-targets-rto--rpo)
3. [Threat model](#threat-model)
4. [Backup architecture](#backup-architecture)
5. [Backup lifecycle](#backup-lifecycle)
6. [Provisioning the backup stack](#provisioning-the-backup-stack)
7. [Day-2 operations](#day-2-operations)
8. [Restore procedure (step-by-step)](#restore-procedure-step-by-step)
9. [Restore drill — weekly + on-demand](#restore-drill--weekly--on-demand)
10. [Drill log template](#drill-log-template)
11. [Troubleshooting](#troubleshooting)
12. [Known gaps + Phase 7 roadmap](#known-gaps--phase-7-roadmap)
13. [Appendix A — S3 IAM policy](#appendix-a--s3-iam-policy)
14. [Appendix B — pgbackrest config reference](#appendix-b--pgbackrest-config-reference)
15. [Appendix C — recovery decision tree](#appendix-c--recovery-decision-tree)

---

## Executive summary

Wake stores **all durable state in Postgres**: sessions, agent configs,
environments, events (append-only log), worker leases, tenancy metadata,
RBAC user/role bindings (Phase 6), and vault audit. **Without Postgres
backups, the system is a Russian roulette: one disk failure, one fat-
finger DROP, one ransomware event, and the entire history is gone.**

Phase 6 ships a production-grade backup workflow built on
**[pgbackrest](https://pgbackrest.org/)** with S3-compatible storage
(AWS S3 / MinIO / Cloudflare R2 / Backblaze B2). The workflow is:

- **Weekly full backup** (Sun 02:00 UTC) — block-level, zstd-compressed
- **Daily incremental backup** (Mon-Sat 02:00 UTC) — only changed blocks
- **30-day rolling retention** (4 weekly fulls + 30 incrementals)
- **Restore drill weekly** — CI provisions throwaway Postgres, restores
  latest backup, asserts row counts + RTO budget
- **In-cluster restore-test** — opt-in `helm test` hook

The chart ships with `backup.enabled: false` by default (opt-in) so
single-node dev installs aren't surprised by an empty S3 bucket. **All
production deployments MUST flip this to true** before going live.

---

## Recovery targets (RTO / RPO)

| Target | Value | Verified by |
|---|---|---|
| **RTO** (Recovery Time Objective) | **< 30 minutes** | Weekly CI drill (`scripts/restore-drill.sh`) + per-upgrade `helm test` hook (optional) |
| **RPO** (Recovery Point Objective) | **< 24 hours** | Daily incremental cadence |
| **Backup availability** | 30 days rolling | Pgbackrest retention policy |
| **Drill cadence** | Weekly | `.github/workflows/restore-drill.yml` (Sun 06:00 UTC) |
| **Cross-region durability** | Per S3 provider | Use S3 cross-region replication if surviving a region loss is in scope |

### What these mean in practice

- **RTO < 30min** = from the moment we decide to restore, the database
  is back online within 30 minutes. Includes pgbackrest restore time +
  Postgres replay time + readiness probe + worker reconnect. Does **not**
  include time to *detect* the incident (that's a separate metric — see
  alerting in [Day-2 operations](#day-2-operations)).
- **RPO < 24h** = worst case, the most recent successful incremental was
  yesterday at 02:00 UTC, so we can lose up to ~24h of events. This is
  the Phase 6 baseline. Tighter RPO requires WAL streaming (Phase 7).
- **Sessions in flight at the moment of disaster** = lost. Workers will
  see their leases evaporate after restore and pick up fresh work.
  Frontend will reconnect SSE.

### Acceptable cost of failure

| Loss | Severity | Mitigation |
|---|---|---|
| Last 24h of events | HIGH but accepted | RPO trade-off; tighten with Phase 7 WAL |
| In-flight sessions | MEDIUM | Idempotent workers re-pick from advisory locks |
| Vault audit trail (24h) | HIGH | Same RPO; cannot relax without WAL |
| User-uploaded artifacts (if any) | OUT OF SCOPE | Not in DB; lives in app-specific S3 bucket |

---

## Threat model

What we defend against:

| Threat | Likelihood | Impact | Backup helps? |
|---|---|---|---|
| Postgres disk failure (PVC corruption) | LOW (managed PG: rare; self-hosted: occasional) | TOTAL | **Yes** — restore from latest |
| Operator drops table / fat-fingers `DELETE FROM events` | MEDIUM | HIGH | **Yes** — restore previous backup |
| Ransomware / malicious encryption of cluster | LOW | TOTAL | **Yes** — backups in *separate* account/bucket |
| Region outage | LOW | TOTAL | **Yes** if cross-region replication; **no** otherwise |
| Application bug corrupts events (logical, not physical) | MEDIUM | MEDIUM | **Yes** — but you may need PITR (Phase 7) |
| Postgres point-version upgrade goes sideways | LOW | HIGH | **Yes** — restore previous + redo migration |
| Adversary obtains S3 keys + deletes backups | LOW | TOTAL | **Mitigated** by S3 object lock + retention lock |
| Restore process itself is broken | UNKNOWN until tested | TOTAL | **Drill mitigates** — weekly verification |
| Backup never actually ran | UNKNOWN until tested | TOTAL | **Drill mitigates** + alert on missing recent backup |

### What backup does NOT protect

- **In-cluster state in worker pods** (in-memory queues): lost at restore
- **Redis pub/sub state**: lost at restore (intentional — events are the
  source of truth)
- **agentgateway proxy state**: stateless, fine
- **Vault credentials**: live in Infisical's own Postgres (same instance
  in Helm default; backed up together)
- **OAuth state tokens (HMAC-signed)**: stateless, fine

### Backup S3 bucket — defense-in-depth checklist

- [ ] **Separate AWS account / GCP project** from the Wake workload
- [ ] **S3 Object Lock** (compliance mode) on backup bucket, 30-day retention
- [ ] **Versioning** enabled (so a malicious overwrite still keeps the old version)
- [ ] **MFA-delete** required for destructive operations
- [ ] **Bucket policy** denying `s3:DeleteObject` from the Wake cluster's IAM principal (use a separate principal for retention pruning, if any)
- [ ] **Server-side encryption** (SSE-S3 or SSE-KMS with a CMK)
- [ ] **Access logging** to a separate bucket
- [ ] **Cross-region replication** (optional, for region survival)

---

## Backup architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                      Wake Kubernetes cluster                       │
│                                                                    │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────────┐    │
│  │ wake-api    │    │ wake-worker  │    │ wake-postgres      │    │
│  │ (Deployment)│◄──►│ (Deployment) │◄──►│ (StatefulSet)      │    │
│  │             │    │              │    │ pg_isready / 5432  │    │
│  └─────────────┘    └──────────────┘    └────────────────────┘    │
│                                                  ▲                 │
│                                                  │ libpq           │
│                                                  │ archive_command │
│                                       ┌──────────┴───────────┐     │
│                                       │ CronJob: backup-full │     │
│                                       │ (Sun 02:00 UTC)      │     │
│                                       └──────────┬───────────┘     │
│                                                  │                 │
│                                       ┌──────────┴───────────┐     │
│                                       │ CronJob: backup-incr │     │
│                                       │ (Mon-Sat 02:00 UTC)  │     │
│                                       └──────────┬───────────┘     │
│                                                  │                 │
│                                                  │ pgbackrest      │
│                                                  │ S3 protocol     │
│                                                  ▼                 │
└──────────────────────────────────────────────┬───────────────────┘
                                               │
                                               ▼
                            ┌─────────────────────────────────────┐
                            │  S3-compatible bucket (separate ac.)│
                            │  s3://wake-backups-prod/            │
                            │   pgbackrest/                       │
                            │     archive/wake-prod/...           │
                            │     backup/wake-prod/               │
                            │       latest/                       │
                            │       20260512-020000F/   (full)    │
                            │       20260513-020001I/   (incr)    │
                            │       20260514-020002I/   (incr)    │
                            └─────────────────────────────────────┘
                                               ▲
                                               │ pgbackrest restore
                                               │
                            ┌──────────────────┴──────────────────┐
                            │  CI: scripts/restore-drill.sh       │
                            │  (Sun 06:00 UTC, weekly)            │
                            └─────────────────────────────────────┘
```

### Why pgbackrest (not pg_dump on cron)

| Concern | pg_dump | pgbackrest |
|---|---|---|
| Lock-free online backup | yes | yes |
| Incremental backups | **no** (always full) | yes (block-level) |
| Compression | gzip stream | zstd parallel |
| Restore tooling | manual `pg_restore` + reconstruct schema | `pgbackrest restore` (1 command) |
| Retention policies | none (you write cron logic) | built-in (`repo1-retention-*`) |
| PITR ready | no | yes (with WAL archiving — Phase 7 toggle) |
| Multi-repo (mirror) | no | yes (2+ repos, independent retention) |
| Parallelism | no | configurable `process-max` |
| Verification | `pg_restore --list` only | `pgbackrest check`, `--type=full,diff,incr` |

**Decision**: pgbackrest. The cost of running pgbackrest is one extra
container image + 2 CronJobs; the win is correctness + first-class
incremental + a real restore command.

---

## Backup lifecycle

```
┌──────────────────────────────────────────────────────────────────┐
│ T0  Helm install --set backup.enabled=true                       │
│     └─ creates configmap, secrets, ServiceAccount, 2x CronJobs   │
│                                                                  │
│ T0+1week  First Sunday 02:00 UTC                                │
│     └─ backup-full CronJob fires                                 │
│         └─ pgbackrest stanza-create (idempotent)                 │
│         └─ pgbackrest --type=full backup                         │
│             └─ writes backup/<stanza>/<timestamp>F/ to S3        │
│                                                                  │
│ T0+1d ... T0+6d   Mon-Sat 02:00 UTC                             │
│     └─ backup-incremental CronJob fires                          │
│         └─ pgbackrest --type=incr backup                         │
│             └─ writes backup/<stanza>/<timestamp>I/ to S3        │
│                                                                  │
│ T0+4 weeks       Retention kicks in                              │
│     └─ Pgbackrest sees `repo1-retention-full=4` exceeded         │
│         └─ deletes oldest full + dependent incrementals          │
│                                                                  │
│ T_drill  Sunday 06:00 UTC (weekly)                              │
│     └─ CI: scripts/restore-drill.sh                              │
│         └─ throwaway Postgres + MinIO                            │
│         └─ pgbackrest restore                                    │
│         └─ assert row counts + RTO < 30min                       │
│         └─ uploads drill-metrics.json (90d retention)            │
│                                                                  │
│ T_disaster  (rare)                                              │
│     └─ Follow Restore procedure (this doc, §8)                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Provisioning the backup stack

### Step 1 — create the S3 bucket

(AWS example; adapt for your provider.)

```bash
aws s3api create-bucket --bucket wake-backups-prod --region us-east-1
aws s3api put-bucket-versioning --bucket wake-backups-prod \
  --versioning-configuration Status=Enabled
aws s3api put-object-lock-configuration --bucket wake-backups-prod \
  --object-lock-configuration '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"COMPLIANCE","Days":30}}}'
aws s3api put-bucket-encryption --bucket wake-backups-prod \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

### Step 2 — create an IAM user (or role) for the backup workload

See [Appendix A](#appendix-a--s3-iam-policy) for the minimal IAM policy.

```bash
aws iam create-user --user-name wake-backup-user
aws iam put-user-policy --user-name wake-backup-user \
  --policy-name wake-backup-policy \
  --policy-document file://wake-backup-policy.json
aws iam create-access-key --user-name wake-backup-user
# Save the AccessKeyId and SecretAccessKey for the next step.
```

### Step 3 — create the Kubernetes Secret (BYO — best practice)

```bash
kubectl create namespace wake --dry-run=client -o yaml | kubectl apply -f -
kubectl -n wake create secret generic wake-backup-s3-creds \
  --from-literal=access-key-id="$AWS_ACCESS_KEY_ID" \
  --from-literal=secret-access-key="$AWS_SECRET_ACCESS_KEY"
```

### Step 4 — Helm install with backup enabled

```bash
helm upgrade --install wake ./deploy/helm/wake \
  --namespace wake \
  --create-namespace \
  --set auth.apiKey="$(openssl rand -hex 32)" \
  --set auth.oauthStateSecret="$(openssl rand -hex 32)" \
  --set backup.enabled=true \
  --set backup.s3.bucket=wake-backups-prod \
  --set backup.s3.endpoint=https://s3.us-east-1.amazonaws.com \
  --set backup.s3.region=us-east-1 \
  --set backup.s3.secretName=wake-backup-s3-creds
```

### Step 5 — verify the CronJobs are scheduled

```bash
kubectl -n wake get cronjob -l app.kubernetes.io/component=backup
# Expect:
# NAME                            SCHEDULE      ...
# wake-backup-full                0 2 * * 0     ...
# wake-backup-incremental         0 2 * * 1-6   ...

# Trigger a manual first full to bootstrap:
kubectl -n wake create job --from=cronjob/wake-backup-full \
  wake-backup-bootstrap-$(date +%s)

# Watch the run:
kubectl -n wake logs -l app.kubernetes.io/component=backup --tail=200 -f
```

Expected output ends with `[wake-backup] complete` followed by a
pgbackrest `info` dump showing one full backup. If you see
`new backup label = ...F` you're golden.

### Step 6 — verify the backup lands in S3

```bash
aws s3 ls s3://wake-backups-prod/pgbackrest/backup/<stanza>/
# Expect a timestamp directory ending in F (full).
```

### Step 7 — wire alerts

Create a Prometheus / Grafana / Datadog alert that fires when:

- Any backup CronJob's last `successful` time is > 26 hours ago
  (allows the 24h cadence + 2h slack)
- Any backup CronJob's last 3 runs failed
- S3 bucket size dropped > 10% week-over-week (catches retention misconfig)
- Restore drill artifact `result` field = `"FAIL"`

Wake doesn't ship these alerts in the chart yet (Phase 7 deliverable —
see Known gaps). For now wire them manually against the
`kube_cronjob_status_last_successful_time` metric exposed by
kube-state-metrics.

---

## Day-2 operations

### List backups

```bash
kubectl -n wake create job --from=cronjob/wake-backup-full \
  wake-backup-info-$(date +%s) -- pgbackrest --stanza=wake-wake info
# OR exec into any backup pod:
kubectl -n wake exec -it $(kubectl -n wake get pod -l backup.wake.dev/type=full -o name | head -1) -- \
  pgbackrest --stanza=wake-wake info
```

Expected output:
```
stanza: wake-wake
    status: ok
    cipher: none

    db (current)
        wal archive min/max (16): 00000001... / 00000001...

        full backup: 20260512-020000F
            timestamp start/stop: 2026-05-12 02:00:00 / 2026-05-12 02:03:21
            wal start/stop: 000000010000000000000005 / 000000010000000000000005
            database size: 142.3MB, database backup size: 142.3MB
            repo1: backup set size: 38.1MB, backup size: 38.1MB

        incr backup: 20260513-020000I
            timestamp start/stop: 2026-05-13 02:00:00 / 2026-05-13 02:00:38
            ...
```

### Manual one-off backup

```bash
# Full
kubectl -n wake create job --from=cronjob/wake-backup-full \
  wake-backup-manual-full-$(date +%s)

# Incremental
kubectl -n wake create job --from=cronjob/wake-backup-incremental \
  wake-backup-manual-incr-$(date +%s)
```

### Change cadence

```bash
helm upgrade wake ./deploy/helm/wake \
  --reuse-values \
  --set backup.schedule.full="0 1 * * 0" \
  --set backup.schedule.incremental="0 1 * * 1-6"
```

### Change retention

```bash
helm upgrade wake ./deploy/helm/wake \
  --reuse-values \
  --set backup.retention.full=8 \
  --set backup.retention.incremental=60
```

### Pause backups (e.g. during major maintenance)

Suspend the CronJobs without removing the chart:

```bash
kubectl -n wake patch cronjob wake-backup-full   -p '{"spec":{"suspend":true}}'
kubectl -n wake patch cronjob wake-backup-incremental -p '{"spec":{"suspend":true}}'

# Resume:
kubectl -n wake patch cronjob wake-backup-full   -p '{"spec":{"suspend":false}}'
kubectl -n wake patch cronjob wake-backup-incremental -p '{"spec":{"suspend":false}}'
```

### Rotate S3 access keys

```bash
# 1. Create a new key in IAM.
aws iam create-access-key --user-name wake-backup-user

# 2. Update the K8s Secret in place.
kubectl -n wake create secret generic wake-backup-s3-creds \
  --from-literal=access-key-id="$NEW_ACCESS_KEY_ID" \
  --from-literal=secret-access-key="$NEW_SECRET_ACCESS_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. Force the next CronJob run to pick up the new Secret.
kubectl -n wake delete jobs -l app.kubernetes.io/component=backup

# 4. Verify the next scheduled run succeeds, then deactivate the old key.
aws iam update-access-key --user-name wake-backup-user --status Inactive \
  --access-key-id "$OLD_ACCESS_KEY_ID"
```

### Switch from inline creds to BYO Secret

```bash
# 1. Create the Secret with the same keys.
kubectl -n wake create secret generic wake-backup-s3-creds \
  --from-literal=access-key-id="$ID" \
  --from-literal=secret-access-key="$SECRET"

# 2. Helm upgrade with secretName + clear inline.
helm upgrade wake ./deploy/helm/wake --reuse-values \
  --set backup.s3.accessKeyId="" \
  --set backup.s3.secretAccessKey="" \
  --set backup.s3.secretName=wake-backup-s3-creds
```

---

## Restore procedure (step-by-step)

This is the **production restore runbook**. Use it when the live Wake
Postgres is unrecoverable or you've decided to roll back to a prior
backup. **Always test restore in a non-prod env first** — see drill.

### Pre-flight (T-30min)

- [ ] **Page on-call** — incident channel + status page update
- [ ] **Confirm the disaster** — is Postgres actually unrecoverable, or
      can a `kubectl rollout restart` fix it? Don't restore unnecessarily.
- [ ] **Decide which backup to restore** — usually the latest, but if
      data corruption is suspected, pick the most recent backup **before**
      corruption started. See `pgbackrest info` output.
- [ ] **Note the timestamp** of the backup you'll restore — record in
      the incident log.
- [ ] **Snapshot the current PVC** if possible (in case restore goes
      sideways, you can compare). On AWS: `aws ec2 create-snapshot ...`.
- [ ] **Tell users** — the dashboard will be down for ~15-30 min.

### Step 1 — stop writers (T+0)

```bash
# Scale API + workers to 0 so nothing writes to PG mid-restore.
kubectl -n wake scale deploy wake-api wake-worker --replicas=0

# Verify no pods remain.
kubectl -n wake get pods -l app.kubernetes.io/component=api
kubectl -n wake get pods -l app.kubernetes.io/component=worker
```

### Step 2 — stop Postgres (T+1min)

```bash
kubectl -n wake scale statefulset wake-postgres --replicas=0

# Wait for the pod to terminate cleanly.
kubectl -n wake wait --for=delete pod/wake-postgres-0 --timeout=2m
```

### Step 3 — restore via a one-shot pod (T+2min)

Create a temporary pod that mounts the Postgres PVC and runs pgbackrest:

```bash
cat <<EOF | kubectl -n wake apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: wake-postgres-restore
  labels:
    app.kubernetes.io/component: backup-restore
spec:
  restartPolicy: Never
  serviceAccountName: wake-backup
  containers:
    - name: pgbackrest
      image: pgbackrest/pgbackrest:2.54.0
      command:
        - /bin/bash
        - -c
        - |
          set -euo pipefail
          STANZA=wake-wake
          # Optionally specify a target time / target backup via --target / --set.
          # For latest backup, no flags needed.
          pgbackrest --stanza="\$STANZA" --pg1-path=/var/lib/postgresql/data --delta restore
          echo "restore complete; chowning data dir..."
          chown -R 999:999 /var/lib/postgresql/data
          echo "done. sleeping to allow inspection..."
          sleep 60
      env:
        - name: PGBACKREST_REPO1_S3_KEY
          valueFrom:
            secretKeyRef:
              name: wake-backup-s3-creds   # or wake-wake-backup-s3 if inline
              key: access-key-id
        - name: PGBACKREST_REPO1_S3_KEY_SECRET
          valueFrom:
            secretKeyRef:
              name: wake-backup-s3-creds
              key: secret-access-key
      volumeMounts:
        - name: pgbackrest-config
          mountPath: /etc/pgbackrest
          readOnly: true
        - name: pgdata
          mountPath: /var/lib/postgresql/data
  volumes:
    - name: pgbackrest-config
      configMap:
        name: wake-wake-pgbackrest
    - name: pgdata
      persistentVolumeClaim:
        claimName: data-wake-postgres-0
EOF

# Watch the restore:
kubectl -n wake logs -f wake-postgres-restore

# Expected output ends with "restore complete".
# RTO clock is ticking — typical 5-15min for < 50GB DB.
```

### Step 4 — bring Postgres back up (T+15min)

```bash
kubectl -n wake delete pod wake-postgres-restore --wait=true

kubectl -n wake scale statefulset wake-postgres --replicas=1

# Wait for readiness.
kubectl -n wake wait --for=condition=ready pod/wake-postgres-0 --timeout=3m
```

### Step 5 — verify data (T+18min)

```bash
kubectl -n wake exec -it wake-postgres-0 -- psql -U wake -d wake -c "
  SELECT COUNT(*) FROM agents;
  SELECT COUNT(*) FROM environments;
  SELECT COUNT(*) FROM sessions;
  SELECT COUNT(*) FROM events;
  SELECT MAX(created_at) FROM sessions;
"
```

Compare row counts against the most recent **known good** snapshot
(e.g. last Grafana dashboard export). Confirm `MAX(created_at)` matches
your expected RPO (no older than 24h ago).

### Step 6 — re-enable writers (T+20min)

```bash
kubectl -n wake scale deploy wake-api wake-worker --replicas=2

kubectl -n wake wait --for=condition=available deploy/wake-api --timeout=2m

# Smoke check.
kubectl -n wake exec -it deploy/wake-api -- \
  curl -sf -H "X-Wake-API-Key: $WAKE_API_KEY" http://localhost:8080/health
```

### Step 7 — re-trigger a fresh backup (T+25min)

The restore brought back the last backup's state, but going forward you
want a fresh full backup to avoid restoring on top of a possibly-stale
backup chain if a second disaster strikes.

```bash
kubectl -n wake create job --from=cronjob/wake-backup-full \
  wake-backup-post-restore-$(date +%s)
```

### Step 8 — write the post-mortem (T+1h)

Capture in the incident log:

- Timeline (each step's actual timestamp)
- Actual RTO vs 30min budget
- Actual RPO (lag between backup time and disaster time)
- Row counts before/after
- Anything that didn't go as documented — file a Phase 7 ticket

---

## Restore drill — weekly + on-demand

### Weekly CI drill

Lives at `.github/workflows/restore-drill.yml`. Runs Sunday 06:00 UTC
(4h after the production full backup at 02:00 UTC, so the drill exercises
fresh data).

```yaml
on:
  schedule:
    - cron: "0 6 * * 0"
```

What it does:

1. Spins up disposable Postgres + MinIO via `docker compose -f
   deploy/docker-compose.yml -f deploy/docker-compose.backup.yml`
2. Seeds 100 rows in each critical table (`sessions`, `events`, `agents`,
   `environments`)
3. Runs `pgbackrest stanza-create + backup --type=full`
4. Truncates the source tables (simulated disaster)
5. Runs `pgbackrest restore` against an empty Postgres
6. Asserts row counts ≥ baseline
7. Asserts wall-clock RTO ≤ 1800s (30 min)
8. Uploads `drill-metrics.json` artifact (90-day retention) for trending

### On-demand drill (local)

From a workstation with Docker installed:

```bash
# Sanity drill — 1min runtime.
./scripts/restore-drill.sh

# Custom budget for slow CI hardware.
RTO_BUDGET_SECONDS=3600 ./scripts/restore-drill.sh

# Inspect leftover artifacts after a failure.
KEEP_ARTIFACTS=1 ./scripts/restore-drill.sh
```

Pass criteria:

- All critical tables restored with row counts ≥ baseline
- RTO within budget
- pgbackrest exit codes 0 throughout

### Drill against production backups (advanced)

You can run the drill **against the actual production S3 bucket** for
maximum realism:

```bash
# Override the S3 endpoint to point at production.
docker run --rm \
  -e PGBACKREST_REPO1_S3_BUCKET=wake-backups-prod \
  -e PGBACKREST_REPO1_S3_ENDPOINT=https://s3.us-east-1.amazonaws.com \
  -e PGBACKREST_REPO1_S3_REGION=us-east-1 \
  -e PGBACKREST_REPO1_S3_KEY="$AWS_ACCESS_KEY_ID" \
  -e PGBACKREST_REPO1_S3_KEY_SECRET="$AWS_SECRET_ACCESS_KEY" \
  pgbackrest/pgbackrest:2.54.0 \
  pgbackrest --stanza=wake-prod info
```

**WARNING**: do NOT run restore against the production cluster's PVC
during a drill. Always use a throwaway target.

---

## Drill log template

Copy this template into your incident / ops log after every drill.

```
============================================================
Wake Restore Drill — <YYYY-MM-DD>
============================================================
Drill ID:        <github-run-id or manual-<timestamp>>
Operator:        <name>
Trigger:         <weekly cron | manual | post-incident>
Source bucket:   <s3://wake-backups-prod | local minio>
Target:          <ephemeral compose | dedicated drill cluster>

Backup snapshot used:
  label:         <e.g. 20260513-020000I>
  type:          <full | diff | incr>
  timestamp:     <YYYY-MM-DD HH:MM:SS UTC>
  size:          <... MB>

Procedure:
  step 1 — provision throwaway PG ........  <PASS/FAIL>  (<duration>)
  step 2 — seed baseline rows ............  <PASS/FAIL>  (<duration>)
  step 3 — backup verified in S3 .........  <PASS/FAIL>  (<duration>)
  step 4 — simulate disaster (truncate)...  <PASS/FAIL>  (<duration>)
  step 5 — pgbackrest restore ............  <PASS/FAIL>  (<duration>)
  step 6 — row count assertions ..........  <PASS/FAIL>
  step 7 — RTO budget assertion ..........  <PASS/FAIL>

Row counts (after restore):
  agents          baseline: 100   actual: 100   ✓
  environments    baseline: 100   actual: 100   ✓
  sessions        baseline: 100   actual: 100   ✓
  events          baseline: 100   actual: 100   ✓

Timings:
  total wall clock:           <X>s
  pgbackrest restore phase:   <Y>s
  postgres bring-up:          <Z>s
  RTO budget:                 1800s
  status:                     <UNDER | OVER> budget

Result:           <PASS | FAIL>

Issues observed:
  - <free-form notes; link issues / file tickets>

Action items:
  [ ] <action 1>
  [ ] <action 2>

Next scheduled drill: <YYYY-MM-DD>
============================================================
```

Archive completed drill logs in `docs/runbook/drill-log/` (create the
directory on first drill). Trending data: extract `total wall clock`
into a spreadsheet to spot degradation over time.

---

## Troubleshooting

### Backup pod CrashLoopBackOff with `S3 - Permission denied`

The S3 creds are wrong or the IAM policy doesn't include `s3:PutObject`
on the bucket. Verify with:

```bash
kubectl -n wake exec -it $(kubectl -n wake get pod -l app.kubernetes.io/component=backup -o name | head -1) -- \
  pgbackrest --stanza=wake-wake check
```

Fix: re-rotate access keys ([Day-2 ops](#day-2-operations)) or update
the IAM policy (see [Appendix A](#appendix-a--s3-iam-policy)).

### Backup runs but produces no incremental — always full

Pgbackrest can't find a prior full backup. Run `pgbackrest info` — if
the output shows zero backups, the first incremental attempt was made
before the first full. Trigger a manual full:

```bash
kubectl -n wake create job --from=cronjob/wake-backup-full \
  wake-backup-bootstrap-$(date +%s)
```

### Restore fails with `archive_command failed`

WAL archiving isn't configured on the source Postgres. For Phase 6
restore-from-backup-only flows this is harmless — pgbackrest can restore
without WAL replay. For PITR you need to enable archiving in
`postgresql.conf`:

```
archive_mode = on
archive_command = 'pgbackrest --stanza=wake-wake archive-push %p'
wal_level = replica
```

This is a **Phase 7 deliverable** — not in scope for Phase 6.

### `pgbackrest info` shows old backups but no recent ones

The CronJob isn't running. Check:

```bash
kubectl -n wake get cronjob -l app.kubernetes.io/component=backup
# Look at LAST SCHEDULE column. If it's stale → CronJob is suspended
# or the controller is paused.

kubectl -n wake describe cronjob wake-backup-full
# Look for Events: at the bottom.
```

Common causes:
- `suspend: true` was set (resume with `kubectl patch`)
- StartingDeadlineSeconds exceeded due to controller pause
- `concurrencyPolicy: Forbid` + a stuck previous job

### Restore drill in CI passes locally but fails in GitHub Actions

GitHub Actions runners have slower disk than typical workstations.
RTO budget may need bumping for CI:

```yaml
env:
  RTO_BUDGET_SECONDS: "2400"  # 40min instead of 30
```

Or invest in self-hosted runners for the drill workflow.

### Restored Postgres won't start: "could not access status of transaction"

Usually means restore was incomplete or interrupted. Re-run pgbackrest
restore with `--delta` again, or do a clean restore (delete data dir
first).

### S3 retention isn't deleting old backups

Pgbackrest retention runs at the end of every backup. If retention
isn't applying:

1. Check `repo1-retention-full` in the ConfigMap — must be > 0.
2. Pgbackrest only counts "expirable" fulls. The current full and any
   full required by a still-valid incremental are kept.
3. Look at backup output: `[INFO]: repo1: 12-1 ... remove`.

If S3 has versioning enabled (it should) the delete is a tombstone, not
a permanent removal. Use a separate S3 Lifecycle rule to expire
old versions after ~60 days.

---

## Known gaps + Phase 7 roadmap

| Gap | Severity | Phase 7 ticket |
|---|---|---|
| RPO > 0 (24h worst case) — no WAL streaming | MEDIUM | enable WAL archiving + tune `archive_timeout` |
| No PITR — restore is to last backup only | MEDIUM | document `--target-time` + `--target-action=promote` |
| No alerting shipped — operator wires manually | LOW | bundle Prometheus rules + Alertmanager config |
| No cross-region replication shipped — operator configures S3 | LOW | document replication setup; add values toggle |
| Backup of Infisical vault is implicit (same PG) | MEDIUM | document explicit verification |
| No backup encryption-at-rest besides S3 SSE | LOW | add `--repo1-cipher-pass` option |
| Drill doesn't exercise real production data | UNKNOWN | add opt-in "drill against prod bucket" mode |
| No automated rollback if restore fails mid-flight | MEDIUM | Helm hook ordering work |
| No metrics emitted by backup CronJobs | LOW | sidecar exporter or text-collector |

---

## Appendix A — S3 IAM policy

Minimal AWS IAM policy for the backup workload. Replace
`wake-backups-prod` with your bucket name.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListBackupBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::wake-backups-prod"
    },
    {
      "Sid": "ReadWriteBackupObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::wake-backups-prod/*"
    }
  ]
}
```

**Note**: `s3:DeleteObject` is required for retention pruning. If you
prefer immutability, omit it and rely on S3 Lifecycle rules to expire
old objects.

For IRSA (EKS) leveraging Workload Identity instead of static keys,
attach the policy to a role with this trust relationship:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<account>:oidc-provider/oidc.eks.<region>.amazonaws.com/id/<oidc-id>"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.eks.<region>.amazonaws.com/id/<oidc-id>:sub": "system:serviceaccount:wake:wake-backup"
        }
      }
    }
  ]
}
```

Then annotate the ServiceAccount in values:

```yaml
serviceAccount:
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::<account>:role/wake-backup-role
```

---

## Appendix B — pgbackrest config reference

The full config is rendered by `templates/configmap-pgbackrest.yaml`.
Defaults below; override via `values.backup.*`.

```ini
[global]
repo1-type=s3
repo1-s3-bucket=<your-bucket>
repo1-s3-endpoint=<your-endpoint>
repo1-s3-region=us-east-1
repo1-s3-uri-style=path
repo1-s3-verify-tls=true
repo1-path=/pgbackrest

# Retention
repo1-retention-full=4
repo1-retention-full-type=count
repo1-retention-archive=30
repo1-retention-archive-type=incr

# Compression — zstd is the modern choice
compress-type=zst
compress-level=3

# Parallelism
process-max=2

# Logging
log-level-console=info
log-level-file=off
log-path=/tmp

# WAL behavior
archive-check=true
start-fast=y

[<stanza-name>]
pg1-host=<wake-postgres-service>
pg1-port=5432
pg1-user=wake
pg1-database=wake
```

For tuning:

- `process-max` — bump to `4`-`8` for backups > 10GB
- `compress-level` — `3` is the sweet spot; `6` for smaller (slower)
- `repo1-retention-full` — bump to `8` for 2 months of fulls
- `repo1-retention-archive` — bump to `90` for 3 months of incrementals
  (assuming daily cadence)

---

## Appendix C — recovery decision tree

```
┌────────────────────────────────────────────────────────┐
│           Wake DB appears unhealthy                    │
└──────────────────────┬─────────────────────────────────┘
                       ▼
        ┌──────────────┴──────────────┐
        │ Is Postgres pod running?    │
        └──────────────┬──────────────┘
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
       NO                             YES
        │                             │
        ▼                             ▼
  Check PVC.            ┌────────────┴─────────────┐
  PV bound?             │  Does `psql -c 'SELECT  │
  Storage class OK?     │   1'` succeed?           │
  │                     └────────────┬─────────────┘
  ▼                                  │
  Fix infra issue                    ▼
  before restoring.            ┌─────┴──────┐
  Restore only if              │  YES       │  NO
  PVC is gone for good.        ▼            ▼
                          Inspect data    Restart pod.
                          quality.        Wait 60s.
                          Logical         If still down,
                          corruption?     check logs for
                          │               crashes.
                          ▼               If WAL replay
                  ┌───────┴────────┐      stuck, restore.
                  │ Recent backup  │
                  │ predates the   │
                  │ corruption?    │
                  └───────┬────────┘
                          ▼
                  ┌───────┴────────┐
                  │  YES → restore │
                  │  to that backup│
                  │                │
                  │  NO  → restore │
                  │  to latest and │
                  │  rebuild lost  │
                  │  data manually │
                  └────────────────┘
```

---

## Sign-off

This runbook is reviewed:

- **Quarterly** during the Wake security review
- **After any incident** that exercises it (post-mortem entry)
- **Before each minor Wake release** if backup paths changed

Owner of last review: tenancy-ops slice, Phase 6 — 2026-05-14.
