# Event Log Retention

> Phase 7 — Tier 1 gap #5. Compact + archive + TTL purge for the Wake
> event log. Without retention, a busy workspace fills its storage with
> 10M+ events in months. This doc explains the three knobs Wake gives
> you and how to use them safely.

## TL;DR

```bash
# Coalesce streaming deltas into single snapshot events (any time).
wake events compact --session=01H...

# Upload events older than 90 days to S3 as JSONL gzip.
wake events archive --before=2026-01-01 --bucket=s3://wake-archive/prod --delete

# In Kubernetes:
helm upgrade wake deploy/helm/wake \
  --set retention.enabled=true \
  --set retention.archive.enabled=true \
  --set retention.archive.s3Bucket=s3://wake-archive/prod \
  --set retention.archive.beforeDays=30
```

That's the contract. The rest of this doc covers when to use each
knob, how restore works, and the safety guarantees.

---

## Why exists

The Wake event log is append-only — every adapter step writes one or
more events. A busy customer session emits dozens of
`assistant.delta` events per second during streaming, plus
`tool_use` / `tool_result` pairs, plus the final `assistant.message`.
At realistic load:

* a typical chat session = 500 events / hour,
* 100 active sessions = 50k events / hour = ~1.2M / day,
* over a year = ~440M events.

The Postgres `events` table (HASH-partitioned 16 ways per Phase 4)
absorbs this comfortably, but **storage is not free**. After 12 months
in production the event table dominates database size. Retention is
the answer.

The Roadmap calls this out as Tier 1 gap #5: "event log cresce pra
sempre; sessões 100k+ inviáveis no replay". Phase 7 ships three
mechanisms to keep storage bounded.

---

## Three mechanisms

### 1. Compact (per-session, opportunistic)

`wake events compact --session=<id>` coalesces contiguous runs of
`assistant.delta` events into single `assistant.message` snapshots and
deletes the deltas. The semantic guarantee:

* `EventLog.events_to_messages(events)` projection is **unchanged**
  before and after compact (deltas are invisible to the Messages
  API projection by spec).
* The snapshot carries `metadata.compacted=true`,
  `metadata.deltas_removed=N`, `metadata.snapshot_of_seq_start/end`
  so audit trails stay forensic.
* Idempotent: re-running compact on a delta-free session is a no-op.

When to use:

* After a long streaming session (1k+ deltas) that's now in `idle`.
* As part of the close-out hook for a session marked
  "ready_for_archive".
* Not for live sessions — compact MAY race with the dispatcher and
  the orchestrator's job is to call it on idle sessions only.

### 2. Archive (per-cutoff, S3 cold storage)

`wake events archive --before=<ISO date> --bucket=s3://...` exports
every event with `created_at < cutoff` as gzipped JSONL and uploads to
S3. Optionally deletes the local rows AFTER the upload verifies.

The strict order:

```text
1. SELECT events WHERE created_at < cutoff (batched)
2. Serialize to JSONL gzip in-memory
3. PutObject → S3
4. HeadObject → verify ETag round-trip
5. (only with --delete) DELETE local rows
```

**We never delete before S3 confirms success.** The contract calls
this out as a hard rule (R7.6) and the implementation enforces it: a
PutObject that returns no ETag raises and exits before any local row
is touched.

For Postgres backends, every archive batch writes one row to the
`archive_log` audit table (migration 0005):

| Column | Meaning |
|---|---|
| `id` | ULID of the batch |
| `workspace_id` | scope (NULL = global) |
| `cutoff` | `--before` passed by operator |
| `s3_bucket` / `s3_key` | destination object |
| `s3_etag` | upload verification handle |
| `session_count` / `event_count` / `bytes_uploaded` | shape |
| `upload_completed_at` | timestamp |
| `delete_completed_at` | NULL until purge succeeds — used to spot stuck batches |

The audit table is best-effort: a failure here MUST NOT roll back the
already-successful upload. Operators see the warning in the CLI
output and can manually patch the audit row later.

### 3. Purge (TTL-only)

For dev / non-archived deployments, `wake events archive
--output=/tmp/receipt.jsonl.gz --before=<date> --delete` doubles as a
purge — write the receipt locally and delete. The Helm CronJob
`retention-purge` uses this pattern.

For production we recommend `archive` (with `--delete`) instead of
purge so the cold data is recoverable.

---

## TTL defaults

The Helm chart ships with conservative defaults:

| Knob | Default | Purpose |
|---|---|---|
| `retention.enabled` | `false` | Master switch (opt-in) |
| `retention.eventsTtlDays` | `90` | Local event log TTL |
| `retention.sessionsTtlDays` | `365` | Session-row TTL (reserved) |
| `retention.archive.enabled` | `false` | Archive CronJob (opt-in) |
| `retention.archive.schedule` | `0 3 * * *` | Daily 03:00 UTC |
| `retention.archive.beforeDays` | `30` | Migrate-to-cold cutoff |
| `retention.archive.batchSize` | `1000` | Events per S3 PutObject |
| `retention.archive.deleteAfterUpload` | `true` | Delete after upload |
| `retention.purge.enabled` | `false` | Purge-only CronJob (opt-in) |
| `retention.purge.schedule` | `30 3 * * *` | Daily 03:30 UTC |

The 90/365 split honours the contract decision:

> "TTL per-table via env (events: 90d, sessions: 365d, archive antes
> de delete). Conservador; tightenable per-customer."

Sessions live 4x longer than events because session metadata (cost,
duration, error count) is the audit-trail "skeleton" — operators
want to know "did session X happen?" long after the per-step events
have been archived.

The session purge is **not** wired in Phase 7 — only event TTL.
`sessionsTtlDays` is reserved for a Phase 8+ knob.

---

## CLI reference

### `wake events compact`

```bash
wake events compact --session=<ID> [--workspace=<WS>] [--database-url=<DSN>]
```

| Option | Default | Description |
|---|---|---|
| `--session, -s` | required | Session ID to compact |
| `--workspace` | None (all) | Workspace scope |
| `--database-url` | `$WAKE_DATABASE_URL` | SQLAlchemy DSN |

Exit codes: 0 success / 1 error / 2 usage.

### `wake events archive`

```bash
wake events archive \
  --before=<ISO date> \
  (--bucket=<S3 URL> | --output=<path>) \
  [--workspace=<WS>] \
  [--batch-size=<N>] \
  [--delete | --no-delete] \
  [--dry-run] \
  [--database-url=<DSN>]
```

| Option | Default | Description |
|---|---|---|
| `--before` | required | ISO-8601 cutoff (2026-01-01 or 2026-01-01T00:00:00Z) |
| `--bucket` | None | `s3://bucket[/prefix]` destination |
| `--output` | None | Local file path (`.jsonl.gz`) |
| `--workspace` | None | Workspace scope |
| `--batch-size` | 1000 | Events per S3 PutObject |
| `--delete` | False | Delete local rows after upload success |
| `--dry-run` | False | Count without uploading or deleting |
| `--database-url` | `$WAKE_DATABASE_URL` | SQLAlchemy DSN |

Exactly one of `--bucket` / `--output` is required (or `--dry-run`).

AWS credentials are picked up via boto3's default chain:

* env `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
* `~/.aws/credentials` profile
* EC2 instance role / EKS IRSA
* Pod-mounted Secret (the Helm CronJob supports `awsSecretRef`)

---

## Helm deployment

The `retention.*` block in `values.yaml` is opt-in (`enabled=false` by
default). To deploy with archive enabled:

```yaml
retention:
  enabled: true
  eventsTtlDays: 90
  archive:
    enabled: true
    schedule: "0 3 * * *"           # daily 03:00 UTC
    beforeDays: 30                  # archive events > 30 days old
    s3Bucket: "s3://wake-archive/prod"
    awsRegion: "us-east-1"
    awsSecretRef:
      name: "wake-archive-aws-creds"  # k/v: access-key-id, secret-access-key
    batchSize: 1000
    deleteAfterUpload: true
  purge:
    enabled: false                   # archive subsumes purge
```

This renders two CronJobs:

* `<release>-retention-archive` — daily archive + delete
* `<release>-retention-purge` — only if `purge.enabled=true`

CronJobs use the same Wake image as the API. They run `wake events
archive` with the configured cutoff and bucket; output goes to
container logs (visible via `kubectl logs job/<name>`).

---

## Restore from archive

Each archive batch is a self-contained gzipped JSONL file. Restore
procedure:

```bash
# 1. Download the batch.
aws s3 cp s3://wake-archive/prod/wake-events-20260101T000000Z-0000.jsonl.gz .

# 2. Decompress + inspect.
gunzip wake-events-20260101T000000Z-0000.jsonl.gz | head -1 | jq

# 3. Bulk-restore via INSERT (Postgres example).
gunzip -c wake-events-20260101T000000Z-0000.jsonl.gz | python -c "
import json, sys
import psycopg
conn = psycopg.connect('$WAKE_DATABASE_URL')
cur = conn.cursor()
for line in sys.stdin:
    ev = json.loads(line)
    cur.execute(\"\"\"
        INSERT INTO events (id, organization_id, workspace_id, session_id,
                            seq, type, payload, parent_id, meta, created_at)
        VALUES (%(id)s, %(organization_id)s, %(workspace_id)s,
                %(session_id)s, %(seq)s, %(type)s, %(payload)s::jsonb,
                %(parent_id)s, %(metadata)s::jsonb, %(created_at)s)
        ON CONFLICT (id, session_id) DO NOTHING
    \"\"\", ev)
conn.commit()
"
```

Things to know:

* The restore is idempotent (ON CONFLICT DO NOTHING). Re-running the
  same archive doesn't double-insert.
* Schema must match the version that produced the archive. Archives
  are NOT migration-safe across major schema changes. If you've
  rolled a schema migration that changes the events table, restore
  the archive into a temporary table and transform.
* `seq` is preserved. Sessions whose `seq` allocations are now
  inconsistent (e.g. partial restore) will fail
  `EventStore.append` invariants — restore whole sessions, not
  ranges of them.

We do NOT ship a `wake events restore` CLI. The above is the
documented manual procedure. A first-class restore is on the Phase 8+
roadmap.

---

## Safety guarantees

1. **Upload-before-delete** — archive NEVER deletes local rows before
   S3 confirms the upload via HeadObject + ETag round-trip.

2. **Bounded batches** — `purge_before` deletes in `batch_size`
   chunks, releasing transactional lock between batches. A 10M-row
   purge does not take a 10-minute exclusive lock.

3. **Workspace scoping** — every CLI command accepts `--workspace`.
   Skipping it scopes to all workspaces (admin-only operation).

4. **Append-only invariant preserved** — `compact` deletes deltas
   but emits a snapshot first. The store NEVER mutates an event
   payload. The `_delete_events` helper is private (underscore-
   prefixed) and only reachable via the documented compact / archive
   flows.

5. **Audit trail** — every Postgres archive writes one
   `archive_log` row. Failures during archive write log the cause
   to structlog at WARN. Operators can grep
   `archive_log.failed_to_write` to find dropped audit rows.

---

## Migration 0005

```python
revision = "0005_retention"
down_revision = "0004_idempotency"
```

Creates the `archive_log` table + two indexes:

* `ix_archive_log_workspace` on `workspace_id`
* `ix_archive_log_upload_completed_at` DESC for recency queries

Both upgrade and downgrade are idempotent (`IF NOT EXISTS` / `IF
EXISTS`). Down migration drops the table; the event log itself is
unaffected by the migration.

The SQLite reference store does NOT include `archive_log` — SQLite
deployments are dev-only and the audit trail is non-essential there.

---

## Operations runbook

### A purge ran too aggressively — how do I recover?

If `archive.deleteAfterUpload=true` and the S3 upload succeeded, the
data is in S3. Find the `archive_log` row for the affected window
and restore from the listed S3 keys (see "Restore from archive"
above).

If `deleteAfterUpload=false` and a manual `wake events archive` ran
with `--delete`, the audit trail is still in `archive_log`.

If you ran `wake events archive --output=...` (local file) with
`--delete` and the file is gone, the data is lost. Hopefully you have
pgbackrest backups from Phase 6.

### Archive jobs are slow / timing out

* Increase `retention.archive.batchSize` (default 1000 → 5000).
* Lower `retention.archive.beforeDays` to migrate less per run.
* Profile the S3 endpoint — non-AWS S3 (MinIO, R2) is sometimes
  rate-limited at 1k PutObject/sec.

### How do I disable retention for a single workspace?

The CronJobs scope to all workspaces. To exclude a workspace, run a
separate `wake events archive --workspace=<excluded-ws>` BEFORE the
cluster-wide CronJob and re-insert from the archive. Less destructive:
schedule the CronJob outside business hours and accept the workspace-
wide pause.

A `--exclude-workspace` flag is on the Phase 8+ roadmap.

---

## Testing

Unit tests in `tests/unit/test_retention.py` and
`tests/unit/test_compact.py` cover:

* `purge_before` dry-run + actual delete + batching + workspace scope
* `iter_for_archive` ordering + batching + cutoff filter
* `compact_session` empty / large / idempotent / multiple runs /
  Messages projection determinism

Run only the retention tests:

```bash
pytest tests/unit/test_retention.py tests/unit/test_compact.py -v
```

---

## Future work

* `wake events restore` first-class CLI (Phase 8+).
* Streaming archive (no in-memory batch) for very-large windows.
* Partition-level archive on Postgres (DETACH partition, dump
  partition, drop partition — single transaction).
* Cross-region replication of archive bucket.
* Workspace-aware exclusion in the CronJob.
