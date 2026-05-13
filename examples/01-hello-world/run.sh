#!/usr/bin/env bash
# 01 — Hello World
# Smoke-tests the Wake server end-to-end. Starts a local server, runs a
# one-shot prompt, then tears the server down.

set -euo pipefail

PORT="${WAKE_PORT:-8080}"
BASE="http://127.0.0.1:${PORT}"
export WAKE_SERVER="${BASE}"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "warn: ANTHROPIC_API_KEY is not set — the harness will fail to call Claude." >&2
fi

echo "[wake] starting server at ${BASE}"
wake server --local --port "${PORT}" >/tmp/wake-server.log 2>&1 &
SERVER_PID=$!
trap 'kill "${SERVER_PID}" 2>/dev/null || true; wait "${SERVER_PID}" 2>/dev/null || true' EXIT

# Poll until the server's TCP socket is up. Curl-free fallback: rely on
# `wake agent list` returning quickly once the API is ready.
for _ in $(seq 1 40); do
  if wake agent list --server "${BASE}" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

echo "[wake] running prompt..."
wake run "Say hello in 3 languages: English, French, Portuguese. One sentence each." \
  --model claude-opus-4-7

echo
echo "[wake] done — server logs at /tmp/wake-server.log"
