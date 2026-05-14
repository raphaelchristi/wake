# Wake Helm chart

Production-grade Kubernetes deployment for the Wake durable agent
runtime. Covers the API tier, worker tier, Postgres event store, Redis
pub/sub, agentgateway egress proxy, Infisical vault, the dashboard
frontend, and (Phase 6) pgbackrest-based backups.

## Quickstart

```bash
helm install wake ./deploy/helm/wake \
  --namespace wake \
  --create-namespace \
  --set auth.apiKey="$(openssl rand -hex 32)" \
  --set auth.oauthStateSecret="$(openssl rand -hex 32)" \
  --set secrets.anthropicApiKey="$ANTHROPIC_API_KEY" \
  --set vault.encryptionKey="$(openssl rand -hex 16)" \
  --set vault.authSecret="$(openssl rand -base64 32)" \
  --set postgres.password="$(openssl rand -hex 16)"
```

For a richer walkthrough see [`docs/DEPLOY-KUBERNETES.md`](../../docs/DEPLOY-KUBERNETES.md).

## Components

| Resource | Default | Notes |
|---|---|---|
| `wake-api` Deployment | 2 replicas | FastAPI + SSE |
| `wake-worker` Deployment | 3 replicas | Harness sessions |
| `wake-frontend` Deployment | 2 replicas | Next.js dashboard |
| `wake-postgres` StatefulSet | 1 replica, 50 GiB PVC | Event store |
| `wake-redis` Deployment | 1 replica | Pub/sub |
| `wake-vault` Deployment | 1 replica | Infisical |
| `wake-agentgateway` Deployment | 1 replica | Egress proxy |
| `wake-backup-full` CronJob | `0 2 * * 0` | Weekly full (opt-in) |
| `wake-backup-incremental` CronJob | `0 2 * * 1-6` | Daily incremental (opt-in) |

## Backup (Phase 6 — Tier 0 gap #3)

The chart bundles a pgbackrest-based backup workflow disabled by default
(`backup.enabled: false`). Production deployments **must** enable it.

### Why pgbackrest

Pgbackrest is the de-facto standard for production Postgres backups in
2025. We chose it over `pg_dump`-on-cron because:

| Concern | pg_dump | pgbackrest |
|---|---|---|
| Online (no lock) | yes | yes |
| Incremental | no (always full) | yes (block-level) |
| Compression | gzip stream | zstd parallel |
| Restore tooling | manual `pg_restore` | first-class `pgbackrest restore` |
| Repository hygiene | none | retention policies built-in |
| PITR readiness | no | yes (with WAL archiving) |

### Enable

Minimum viable config:

```yaml
backup:
  enabled: true
  s3:
    endpoint: "https://s3.amazonaws.com"
    bucket: "wake-backups-prod"
    region: "us-east-1"
    # Best practice: pre-create the Secret manually with kubectl /
    # sealed-secrets / external-secrets-operator and reference it by name.
    secretName: "wake-backup-s3-creds"
```

The referenced Secret must contain two keys:

```bash
kubectl -n wake create secret generic wake-backup-s3-creds \
  --from-literal=access-key-id="$AWS_ACCESS_KEY_ID" \
  --from-literal=secret-access-key="$AWS_SECRET_ACCESS_KEY"
```

Inline creds (dev only — not recommended for prod):

```yaml
backup:
  enabled: true
  s3:
    endpoint: "https://s3.amazonaws.com"
    bucket: "wake-backups-prod"
    accessKeyId: "AKIA..."
    secretAccessKey: "..."
```

### Cadence + retention

```yaml
backup:
  schedule:
    full: "0 2 * * 0"        # weekly full (Sun 02:00 UTC)
    incremental: "0 2 * * 1-6"  # daily incremental (Mon-Sat 02:00 UTC)
  retention:
    full: 4    # 4 weeks of full backups
    incremental: 30  # 30 daily incrementals
  processMax: 2  # parallelism for compression/upload
```

### S3-compatible alternatives

| Provider | Endpoint | Notes |
|---|---|---|
| AWS S3 | leave empty (auto-derived) | Use IRSA for keyless auth |
| MinIO | `http://minio.minio.svc:9000` | Set `s3.uriStyle: path` |
| Cloudflare R2 | `https://<account>.r2.cloudflarestorage.com` | Set `s3.uriStyle: path` |
| Backblaze B2 | `https://s3.<region>.backblazeb2.com` | S3-compatible mode |

### IRSA / Workload Identity

To avoid static access keys, set up IAM Roles for Service Accounts (AWS)
or Workload Identity (GCP) and annotate the backup ServiceAccount:

```yaml
serviceAccount:
  annotations:
    eks.amazonaws.com/role-arn: "arn:aws:iam::<acct>:role/wake-backup-role"
```

Then leave `backup.s3.accessKeyId` / `secretAccessKey` empty AND set
`s3.secretName` to an empty Secret (pgbackrest picks up creds from the
instance metadata service via the SA).

### Restore drill

Two-layer drill:

1. **In-cluster smoke** — `backup.restoreTest.enabled: true` adds a
   Helm `test` hook. Run `helm test wake` to restore latest backup into
   a throwaway PVC and assert RTO < 30 minutes.
2. **CI drill** — `.github/workflows/restore-drill.yml` runs
   `scripts/restore-drill.sh` weekly. Spins a throwaway Postgres,
   restores latest backup, asserts row counts on `sessions` / `events` /
   `agents` / `environments`, asserts RTO < 30 minutes. Failure is paged.

### Verify CronJobs

```bash
kubectl -n wake get cronjob -l app.kubernetes.io/component=backup
kubectl -n wake get jobs -l app.kubernetes.io/component=backup
kubectl -n wake logs -l app.kubernetes.io/component=backup --tail=200
```

### Manual one-off backup

```bash
kubectl -n wake create job --from=cronjob/wake-backup-full \
  wake-backup-manual-$(date +%s)
```

### Manual restore

See [`docs/DISASTER-RECOVERY.md`](../../docs/DISASTER-RECOVERY.md) for
the full step-by-step procedure. TL;DR:

```bash
# 1. Scale workloads to 0 to prevent writes.
kubectl -n wake scale deploy wake-api wake-worker --replicas=0

# 2. Run pgbackrest restore against an empty data dir.
kubectl -n wake exec -it wake-postgres-0 -- bash
pgbackrest --stanza=wake-wake --delta restore

# 3. Start Postgres + verify.
kubectl -n wake delete pod wake-postgres-0  # restart
kubectl -n wake scale deploy wake-api wake-worker --replicas=2
```

## Tenant + RBAC (Phase 6)

Phase 6 also ships tenancy headers and RBAC. Both are off by default for
backward compatibility:

```yaml
# In a future values.yaml release:
# rbac:
#   enabled: false   # set true to enforce role checks
```

See [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) and
[`docs/RBAC.md`](../../docs/RBAC.md) (when slice A merges).

## Values reference

The full set of options lives in [`values.yaml`](./values.yaml) — every
field is documented inline. Highlights:

| Path | Default | Notes |
|---|---|---|
| `auth.required` | `true` | Fail-closed API |
| `auth.apiKey` | `""` | Required if `apiKeySecretRef` empty |
| `api.replicas` | `2` | Behind ingress |
| `worker.replicas` | `3` | Pull-based via Postgres locks |
| `postgres.enabled` | `true` | Disable for managed PG |
| `backup.enabled` | `false` | Opt-in (Phase 6) |
| `backup.schedule.full` | `0 2 * * 0` | Cron UTC |
| `backup.retention.full` | `4` | Keep 4 weekly fulls |
| `vault.enabled` | `true` | Infisical |

## Linting

```bash
helm lint deploy/helm/wake
helm template wake deploy/helm/wake \
  --set auth.apiKey=test --set auth.oauthStateSecret=test \
  --set backup.enabled=true --set backup.s3.bucket=test \
  --set backup.s3.accessKeyId=k --set backup.s3.secretAccessKey=s \
  | kubectl apply --dry-run=client -f -
```

## See also

- [`docs/DEPLOY-KUBERNETES.md`](../../docs/DEPLOY-KUBERNETES.md) — full deployment guide
- [`docs/DISASTER-RECOVERY.md`](../../docs/DISASTER-RECOVERY.md) — backup + restore runbook
- [`docs/RUNBOOK.md`](../../docs/RUNBOOK.md) — incident playbooks
