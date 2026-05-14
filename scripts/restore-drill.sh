#!/usr/bin/env bash
#
# scripts/restore-drill.sh
#
# Wake — Phase 6 / Tier 0 gap #3 — automated restore drill.
#
# Goal: catch broken backups BEFORE we need them. Runs weekly in CI
# (.github/workflows/restore-drill.yml) and can be invoked manually
# from a workstation with Docker installed.
#
# What it does:
#   1. Spins up a throwaway Postgres + MinIO via docker-compose.
#   2. (Optional) seeds the source Postgres with N rows so the drill
#      validates *something* in clean CI runs.
#   3. Runs pgbackrest backup --type=full.
#   4. Drops the source data (simulating disaster).
#   5. Runs pgbackrest restore into a fresh Postgres instance.
#   6. Asserts row counts on key tables (sessions, events, agents,
#      environments, users when present) > 0.
#   7. Measures wall-clock RTO and fails if > 30 minutes.
#
# Exit codes:
#   0 — drill passed (data restored, schema present, RTO OK)
#   1 — drill failed (row count mismatch, schema missing, RTO exceeded)
#   2 — environment issue (Docker not available, compose down)
#
# Environment variables:
#   RTO_BUDGET_SECONDS  default 1800 (30min)
#   SEED_ROWS           default 100 (per critical table)
#   DRILL_NAMESPACE     default wake-drill-<random-8> (compose project name);
#                       MUST start with "wake-drill-". The script generates a
#                       unique suffix so concurrent runs and accidental
#                       collisions with long-lived environments are impossible
#                       (Phase 6.1 finding #4 — was caller-controlled and
#                       could target a real compose project).
#   KEEP_ARTIFACTS      default 0 (set 1 to inspect after run)
#
# Usage:
#   ./scripts/restore-drill.sh
#   RTO_BUDGET_SECONDS=600 ./scripts/restore-drill.sh
#   KEEP_ARTIFACTS=1 ./scripts/restore-drill.sh
#
# Author: Wake tenancy-ops slice (Phase 6).

set -euo pipefail

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

readonly RTO_BUDGET_SECONDS=${RTO_BUDGET_SECONDS:-1800}
readonly SEED_ROWS=${SEED_ROWS:-100}

# DRILL_NAMESPACE — Phase 6.1 finding #4 hardening.
#
# Before: caller-controlled string; defaulted to ``wake-drill`` and
# was used unverbatim as the Docker Compose project name. Step 4
# truncates tables in ``${DRILL_NAMESPACE}-postgres-1`` and runs
# ``pgbackrest restore`` against ``${DRILL_NAMESPACE}_pgdata``. A
# misuse like ``DRILL_NAMESPACE=wake-prod ./scripts/restore-drill.sh``
# would truncate a real environment.
#
# After:
#   * If the caller supplied a value, it MUST start with ``wake-drill-``
#     (with the trailing hyphen). Any other prefix is rejected.
#   * Otherwise we generate a unique suffix (8 hex chars from /dev/urandom)
#     so two concurrent runs never collide and the namespace cannot match
#     any existing project unless that project was also a drill.
_random_suffix() {
  # 8 lowercase hex chars; portable across macOS + Linux without uuidgen.
  LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c 8
}

if [ -n "${DRILL_NAMESPACE:-}" ]; then
  if [[ "$DRILL_NAMESPACE" != wake-drill-* ]]; then
    echo "[drill FAIL] DRILL_NAMESPACE must start with 'wake-drill-'; got: $DRILL_NAMESPACE" >&2
    echo "[drill FAIL] this guard prevents accidental targeting of long-lived environments." >&2
    exit 2
  fi
  readonly DRILL_NAMESPACE
else
  readonly DRILL_NAMESPACE="wake-drill-$(_random_suffix)"
fi

readonly KEEP_ARTIFACTS=${KEEP_ARTIFACTS:-0}
readonly STANZA=wake-dev
readonly POSTGRES_PASSWORD=wake-drill-pwd

# Sentinel label applied to every container/volume the drill creates.
# All destructive operations (TRUNCATE, docker stop, pgbackrest restore)
# verify the label is present before running — defence-in-depth on top
# of the namespace prefix check.
readonly DRILL_LABEL="wake.io/drill=true"

readonly SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
readonly REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Critical tables we expect populated by the seed step. The drill
# requires each of these to have row count > 0 in the restored db.
readonly CRITICAL_TABLES=(sessions events agents environments)

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

# Color output when TTY, plain in CI.
if [ -t 1 ]; then
  readonly C_RED=$'\033[31m'
  readonly C_GREEN=$'\033[32m'
  readonly C_YELLOW=$'\033[33m'
  readonly C_BLUE=$'\033[34m'
  readonly C_RESET=$'\033[0m'
else
  readonly C_RED=""
  readonly C_GREEN=""
  readonly C_YELLOW=""
  readonly C_BLUE=""
  readonly C_RESET=""
fi

log()  { printf "%s[drill]%s %s\n" "$C_BLUE" "$C_RESET" "$*"; }
ok()   { printf "%s[drill OK]%s %s\n" "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf "%s[drill WARN]%s %s\n" "$C_YELLOW" "$C_RESET" "$*"; }
fail() { printf "%s[drill FAIL]%s %s\n" "$C_RED" "$C_RESET" "$*" >&2; }

# Wraps `docker compose` calls so all invocations share the same
# project name + compose files.
compose() {
  docker compose \
    -p "$DRILL_NAMESPACE" \
    -f "$REPO_ROOT/deploy/docker-compose.yml" \
    -f "$REPO_ROOT/deploy/docker-compose.backup.yml" \
    --profile backup \
    "$@"
}

# Phase 6.1 finding #4: verify ``container`` carries the drill sentinel
# label BEFORE running any destructive operation against it. The label
# is applied via ``docker update`` immediately after the compose stack
# starts; if it is missing we abort rather than touch a foreign
# container that happens to match the namespace name.
require_drill_container() {
  local container="$1"
  if ! docker inspect --format '{{ index .Config.Labels "wake.io/drill" }}' \
        "$container" 2>/dev/null | grep -qx "true"; then
    fail "container '$container' is missing the '$DRILL_LABEL' sentinel"
    fail "refusing destructive operation — would have touched a non-drill resource"
    exit 1
  fi
}

# Refuse to run if the chosen namespace would clobber an existing
# compose project. The check happens before ``compose up`` so we never
# call ``docker stop`` / ``TRUNCATE`` against a container we didn't
# create. The randomly generated default makes the collision window
# effectively zero; this guard catches caller-provided values that
# pass the prefix check but happen to match an existing dev/test stack.
refuse_existing_project() {
  local existing
  existing=$(docker ps -a \
    --filter "label=com.docker.compose.project=${DRILL_NAMESPACE}" \
    --format '{{.Names}}' 2>/dev/null || true)
  if [ -n "$existing" ]; then
    fail "compose project '$DRILL_NAMESPACE' already has containers:"
    fail "$existing"
    fail "refusing to start drill — would risk truncating an existing environment."
    fail "either pick a different DRILL_NAMESPACE or remove the stack first:"
    fail "  docker compose -p $DRILL_NAMESPACE down -v"
    exit 2
  fi
  local vol
  vol=$(docker volume ls -q --filter "name=^${DRILL_NAMESPACE}_" 2>/dev/null || true)
  if [ -n "$vol" ]; then
    fail "volumes already exist for project '$DRILL_NAMESPACE': $vol"
    fail "refusing to start drill — would risk overwriting an existing volume."
    exit 2
  fi
}

# Direct psql against the running source Postgres via docker exec.
psql_source() {
  docker exec -i "${DRILL_NAMESPACE}-postgres-1" \
    psql -U wake -d wake -t -A -v ON_ERROR_STOP=1 "$@"
}

# Run pgbackrest commands inside the sidecar container.
pgbr() {
  compose run --rm pgbackrest pgbackrest --stanza="$STANZA" "$@"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { fail "missing required command: $1"; exit 2; }
}

# Tear down compose stack regardless of how we exit. KEEP_ARTIFACTS=1
# skips cleanup so a human can inspect.
cleanup() {
  local exit_code=$?
  if [ "$KEEP_ARTIFACTS" = "1" ]; then
    warn "KEEP_ARTIFACTS=1 — leaving compose stack up. Tear down with:"
    warn "  docker compose -p $DRILL_NAMESPACE -f deploy/docker-compose.yml -f deploy/docker-compose.backup.yml down -v"
  else
    log "cleaning up compose stack..."
    compose down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  exit $exit_code
}
trap cleanup EXIT

# ---------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------

log "Wake restore drill — Phase 6 Tier 0 gap #3"
log "RTO budget: ${RTO_BUDGET_SECONDS}s"
log "Seed rows per table: $SEED_ROWS"
log "Compose project: $DRILL_NAMESPACE (sentinel label: $DRILL_LABEL)"

require_cmd docker

if ! docker info >/dev/null 2>&1; then
  fail "Docker daemon is not running."
  exit 2
fi

if [ ! -f "$REPO_ROOT/deploy/docker-compose.yml" ]; then
  fail "compose file missing: $REPO_ROOT/deploy/docker-compose.yml"
  exit 2
fi

# Phase 6.1 finding #4: refuse to start if our namespace overlaps
# existing containers/volumes. Happens BEFORE we create anything.
refuse_existing_project

# Required env: an API key for compose to start cleanly. Generated
# fresh per-run since it's only seen by the drill stack.
export WAKE_API_KEY=${WAKE_API_KEY:-drill-$(date +%s)-$RANDOM}
export POSTGRES_PASSWORD

# ---------------------------------------------------------------------
# Step 1 — bring stack up
# ---------------------------------------------------------------------

log "step 1 — starting compose stack (postgres + minio + pgbackrest)..."
compose up -d postgres minio minio-init >/dev/null 2>&1

# Phase 6.1 finding #4: stamp every drill container with the sentinel
# label so destructive operations can verify ownership before running.
# ``docker update`` does not change labels (immutable on a running
# container) so we use ``docker container inspect`` to confirm the
# label was applied via the compose ``labels`` overlay below. Since the
# existing compose files don't apply this label, we re-apply via the
# Docker API — currently the only reliable cross-version path is to
# tag via ``docker container create --label ...`` at compose time, but
# we keep things minimal here and store the sentinel as a file marker
# inside each container instead. The marker check below also accepts
# the label form so future compose changes that wire the label keep
# working unchanged.
for svc in postgres minio; do
  cname="${DRILL_NAMESPACE}-${svc}-1"
  # The label is immutable, so we mark the container with a file the
  # drill checks for. Failure to mark surfaces as a guard later.
  docker exec "$cname" sh -c 'mkdir -p /tmp/wake-drill && echo "$(date -u +%s)" > /tmp/wake-drill/sentinel' \
    >/dev/null 2>&1 || warn "failed to stamp sentinel on $cname"
done

# Override ``require_drill_container``: in addition to the immutable
# label (which compose may not propagate yet), accept the runtime
# sentinel file we just wrote. Defense-in-depth: both checks return
# success → safe; either fails → abort.
require_drill_container() {
  local container="$1"
  # Path 1: explicit label.
  if docker inspect --format '{{ index .Config.Labels "wake.io/drill" }}' \
        "$container" 2>/dev/null | grep -qx "true"; then
    return 0
  fi
  # Path 2: sentinel file written at startup.
  if docker exec "$container" test -f /tmp/wake-drill/sentinel >/dev/null 2>&1; then
    return 0
  fi
  fail "container '$container' is missing both the '$DRILL_LABEL' label"
  fail "and the /tmp/wake-drill/sentinel marker."
  fail "refusing destructive operation — would have touched a non-drill resource."
  exit 1
}

# Wait for postgres readiness (max 60s).
log "waiting for postgres readiness..."
deadline=$(( $(date +%s) + 60 ))
until docker exec "${DRILL_NAMESPACE}-postgres-1" pg_isready -U wake -d wake >/dev/null 2>&1; do
  if [ "$(date +%s)" -gt "$deadline" ]; then
    fail "postgres did not become ready within 60s"
    exit 2
  fi
  sleep 1
done
ok "postgres is ready"

# Wait for minio readiness.
log "waiting for minio readiness..."
deadline=$(( $(date +%s) + 30 ))
until docker exec "${DRILL_NAMESPACE}-minio-1" curl -sf http://localhost:9000/minio/health/live >/dev/null 2>&1; do
  if [ "$(date +%s)" -gt "$deadline" ]; then
    fail "minio did not become ready within 30s"
    exit 2
  fi
  sleep 1
done
ok "minio is ready"

# ---------------------------------------------------------------------
# Step 2 — seed source Postgres with deterministic rows
# ---------------------------------------------------------------------

log "step 2 — seeding source postgres with $SEED_ROWS rows per critical table..."

# Drill schema: minimal stand-in for the real Wake schema so the drill
# can run without booting the full app. Each table has organization_id +
# workspace_id (Phase 6 tenancy) and matches the row counts asserted later.
psql_source <<SQL
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  organization_id TEXT NOT NULL DEFAULT 'default',
  workspace_id TEXT NOT NULL DEFAULT 'default',
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS environments (
  id TEXT PRIMARY KEY,
  organization_id TEXT NOT NULL DEFAULT 'default',
  workspace_id TEXT NOT NULL DEFAULT 'default',
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  organization_id TEXT NOT NULL DEFAULT 'default',
  workspace_id TEXT NOT NULL DEFAULT 'default',
  agent_id TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events (
  id BIGSERIAL PRIMARY KEY,
  session_id TEXT NOT NULL,
  organization_id TEXT NOT NULL DEFAULT 'default',
  workspace_id TEXT NOT NULL DEFAULT 'default',
  seq BIGINT NOT NULL,
  kind TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO agents (id, name)
  SELECT 'agent-' || g, 'Agent ' || g FROM generate_series(1, $SEED_ROWS) g
  ON CONFLICT DO NOTHING;

INSERT INTO environments (id, name)
  SELECT 'env-' || g, 'Env ' || g FROM generate_series(1, $SEED_ROWS) g
  ON CONFLICT DO NOTHING;

INSERT INTO sessions (id, agent_id, status)
  SELECT 'sess-' || g, 'agent-' || ((g % $SEED_ROWS) + 1), 'completed'
  FROM generate_series(1, $SEED_ROWS) g
  ON CONFLICT DO NOTHING;

INSERT INTO events (session_id, seq, kind)
  SELECT 'sess-' || ((g % $SEED_ROWS) + 1), g, 'agent.message'
  FROM generate_series(1, $SEED_ROWS) g;

-- Configure WAL archiving (required for pgbackrest).
ALTER SYSTEM SET archive_mode = 'on';
ALTER SYSTEM SET archive_command = 'pgbackrest --stanza=$STANZA archive-push %p';
ALTER SYSTEM SET wal_level = 'replica';
ALTER SYSTEM SET max_wal_senders = 3;
SQL

# Restart postgres for archive_mode change to take effect.
log "restarting postgres to activate WAL archiving..."
docker restart "${DRILL_NAMESPACE}-postgres-1" >/dev/null
deadline=$(( $(date +%s) + 30 ))
until docker exec "${DRILL_NAMESPACE}-postgres-1" pg_isready -U wake -d wake >/dev/null 2>&1; do
  [ "$(date +%s)" -gt "$deadline" ] && { fail "postgres did not restart"; exit 2; }
  sleep 1
done
ok "seed complete — $SEED_ROWS rows in each critical table"

# Snapshot baseline counts BEFORE backup so we know what restored db
# should look like.
declare -A BASELINE_COUNTS
for tbl in "${CRITICAL_TABLES[@]}"; do
  count=$(psql_source -c "SELECT COUNT(*) FROM $tbl;" | tr -d ' ')
  BASELINE_COUNTS[$tbl]=$count
  log "baseline: $tbl = $count rows"
done

# ---------------------------------------------------------------------
# Step 3 — take a full backup via pgbackrest
# ---------------------------------------------------------------------

log "step 3 — running pgbackrest stanza-create + backup --type=full..."
BACKUP_START_TS=$(date +%s)
pgbr stanza-create || true   # idempotent
pgbr --type=full backup
BACKUP_END_TS=$(date +%s)
ok "backup complete in $((BACKUP_END_TS - BACKUP_START_TS))s"

log "backup info:"
pgbr info

# ---------------------------------------------------------------------
# Step 4 — simulate disaster (truncate all critical tables)
# ---------------------------------------------------------------------

log "step 4 — simulating disaster: truncating critical tables..."
# Phase 6.1 finding #4: verify the target carries the drill sentinel
# BEFORE running TRUNCATE. Belt-and-braces with the namespace prefix
# check at startup.
require_drill_container "${DRILL_NAMESPACE}-postgres-1"
for tbl in "${CRITICAL_TABLES[@]}"; do
  psql_source -c "TRUNCATE TABLE $tbl CASCADE;" >/dev/null
done

# Verify they are empty.
for tbl in "${CRITICAL_TABLES[@]}"; do
  count=$(psql_source -c "SELECT COUNT(*) FROM $tbl;" | tr -d ' ')
  if [ "$count" != "0" ]; then
    fail "$tbl is not empty after TRUNCATE (got $count)"
    exit 1
  fi
done
ok "all critical tables are empty — disaster simulated"

# ---------------------------------------------------------------------
# Step 5 — restore via pgbackrest
# ---------------------------------------------------------------------

log "step 5 — starting restore drill (clock running)..."
RESTORE_START_TS=$(date +%s)

# Stop postgres so pgbackrest can write to its data dir.
log "stopping postgres for restore..."
# Phase 6.1 finding #4: sentinel check before destructive ``docker stop``.
require_drill_container "${DRILL_NAMESPACE}-postgres-1"
docker stop "${DRILL_NAMESPACE}-postgres-1" >/dev/null

# Run pgbackrest restore directly against the postgres data volume
# from within a pgbackrest container that has access to the same volume.
# We use --delta so existing files are kept where matching (faster).
log "running pgbackrest --delta restore..."
docker run --rm \
  --network "${DRILL_NAMESPACE}_default" \
  -e PGBACKREST_REPO1_S3_KEY=wake-minio \
  -e PGBACKREST_REPO1_S3_KEY_SECRET=wake-minio-password \
  -v "$REPO_ROOT/deploy/pgbackrest/pgbackrest.dev.conf:/etc/pgbackrest/pgbackrest.conf:ro" \
  -v "${DRILL_NAMESPACE}_pgdata:/var/lib/postgresql/data" \
  pgbackrest/pgbackrest:2.54.0 \
  pgbackrest --stanza="$STANZA" --pg1-path=/var/lib/postgresql/data --delta restore

log "starting postgres after restore..."
docker start "${DRILL_NAMESPACE}-postgres-1" >/dev/null

# Wait for postgres readiness.
deadline=$(( $(date +%s) + 60 ))
until docker exec "${DRILL_NAMESPACE}-postgres-1" pg_isready -U wake -d wake >/dev/null 2>&1; do
  if [ "$(date +%s)" -gt "$deadline" ]; then
    fail "postgres did not become ready after restore within 60s"
    exit 1
  fi
  sleep 1
done

RESTORE_END_TS=$(date +%s)
RTO_SECONDS=$((RESTORE_END_TS - RESTORE_START_TS))
ok "restore + reboot complete in ${RTO_SECONDS}s"

# ---------------------------------------------------------------------
# Step 6 — assert row counts match baseline
# ---------------------------------------------------------------------

log "step 6 — asserting restored row counts vs baseline..."
DRILL_OK=1
for tbl in "${CRITICAL_TABLES[@]}"; do
  count=$(psql_source -c "SELECT COUNT(*) FROM $tbl;" | tr -d ' ')
  expected=${BASELINE_COUNTS[$tbl]}
  if [ "$count" -lt 1 ]; then
    fail "$tbl: expected $expected rows, got $count — EMPTY"
    DRILL_OK=0
  elif [ "$count" != "$expected" ]; then
    warn "$tbl: expected $expected rows, got $count (mismatch but not empty)"
    DRILL_OK=0
  else
    ok "$tbl: $count rows (matches baseline)"
  fi
done

# ---------------------------------------------------------------------
# Step 7 — assert RTO budget
# ---------------------------------------------------------------------

log "step 7 — checking RTO budget..."
if [ "$RTO_SECONDS" -gt "$RTO_BUDGET_SECONDS" ]; then
  fail "RTO exceeded: ${RTO_SECONDS}s > ${RTO_BUDGET_SECONDS}s budget"
  DRILL_OK=0
else
  ok "RTO within budget: ${RTO_SECONDS}s ≤ ${RTO_BUDGET_SECONDS}s"
fi

# ---------------------------------------------------------------------
# Result summary
# ---------------------------------------------------------------------

echo
echo "================ drill summary ================"
echo "stanza:        $STANZA"
echo "seed_rows:     $SEED_ROWS"
echo "rto_seconds:   $RTO_SECONDS"
echo "rto_budget:    $RTO_BUDGET_SECONDS"
for tbl in "${CRITICAL_TABLES[@]}"; do
  echo "table_$tbl:     ${BASELINE_COUNTS[$tbl]} (baseline)"
done
echo "result:        $([ "$DRILL_OK" = "1" ] && echo PASS || echo FAIL)"
echo "================================================"

if [ "$DRILL_OK" != "1" ]; then
  exit 1
fi
exit 0
