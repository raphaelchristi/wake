#!/usr/bin/env bash
# 02 — Coding Refactor
# Spins up wake locally, creates a refactor agent + environment, and
# asks it to convert a class-based greeter into a function/closure
# version, watching events live.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${WAKE_PORT:-8080}"
BASE="http://127.0.0.1:${PORT}"
export WAKE_SERVER="${BASE}"

WORKSPACE="$(mktemp -d -t wake-refactor.XXXXXX)"
cp -R "${HERE}/test_repo/." "${WORKSPACE}/"
echo "[wake] workspace: ${WORKSPACE}"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "warn: ANTHROPIC_API_KEY is not set — the harness will fail to call Claude." >&2
fi

echo "[wake] starting server at ${BASE}"
wake server --local --port "${PORT}" >/tmp/wake-server.log 2>&1 &
SERVER_PID=$!
trap 'kill "${SERVER_PID}" 2>/dev/null || true; wait "${SERVER_PID}" 2>/dev/null || true' EXIT

for _ in $(seq 1 40); do
  if wake agent list --server "${BASE}" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

echo "[wake] creating environment from wake.yaml..."
ENV_ID="$(wake environment create \
  --name python-dev \
  --config "${HERE}/wake.yaml" \
  --id-only)"
echo "environment: ${ENV_ID}"

echo "[wake] creating agent refactor-bot..."
AGENT_ID="$(wake agent create \
  --name refactor-bot \
  --model claude-opus-4-7 \
  --system "You refactor Python code using tools. Be concise." \
  --tools bash,file_read,file_write,file_edit \
  --id-only)"
echo "agent: ${AGENT_ID}"

if [[ -z "${AGENT_ID}" ]]; then
  echo "error: empty agent id" >&2
  exit 1
fi

echo "[wake] creating session..."
if [[ -n "${ENV_ID}" ]]; then
  SESSION_ID="$(wake session create --agent "${AGENT_ID}" --environment "${ENV_ID}" --id-only)"
else
  SESSION_ID="$(wake session create --agent "${AGENT_ID}" --id-only)"
fi
echo "session: ${SESSION_ID}"

if [[ -z "${SESSION_ID}" ]]; then
  echo "error: empty session id" >&2
  exit 1
fi

echo "[wake] sending refactor instruction..."
wake session send "${SESSION_ID}" \
  "Refactor test_repo/utils.py: replace the Greeter class with a make_greeter(prefix) function returning a callable, plus a free shout() function. Update main.py to use the new API. Workspace root: ${WORKSPACE}"

echo "[wake] streaming events (Ctrl+C to stop early)..."
wake session stream "${SESSION_ID}"

echo
echo "[wake] tool calls observed:"
wake session events "${SESSION_ID}" --tool-only

echo
echo "[wake] diff vs. starting state:"
diff -r "${HERE}/test_repo" "${WORKSPACE}" || true

echo "[wake] done — workspace at ${WORKSPACE}, server log at /tmp/wake-server.log"
