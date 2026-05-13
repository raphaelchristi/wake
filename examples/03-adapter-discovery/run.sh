#!/usr/bin/env bash
# 03 — Adapter Discovery
# Installs the two Phase 2 stub adapters, lists what Wake's registry
# discovers via entry points, and calls step() against each — proving
# that different adapters produce different outputs.
#
# No Wake server is started: this is a pure adapter-API demo. Until
# the CLI exposes `wake adapter list` (Phase 3), the inline Python
# below is the canonical way to introspect the registry.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"

PY="${PYTHON:-python3}"
if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PY="${REPO_ROOT}/.venv/bin/python"
fi

echo "[wake] python: ${PY}"
echo "[wake] installing stub adapters from the monorepo..."
"${PY}" -m pip install --quiet \
  -e "${REPO_ROOT}/adapters/langgraph" \
  -e "${REPO_ROOT}/adapters/crewai"

echo
echo "[wake] discovered adapters via the 'wake.adapters' entry-point group:"
"${PY}" - <<'PY'
from wake.adapters import AdapterRegistry

registry = AdapterRegistry()
registry.discover()

if not registry.names():
    raise SystemExit("no adapters discovered — stub install likely failed")

for adapter in registry.list():
    print(f"  {adapter.name}@{adapter.version}".ljust(28),
          f"compat={adapter.compatibility}")
PY

echo
echo "[wake] calling step() against each adapter (no LLM, no server)..."
"${PY}" - <<'PY'
import asyncio
from datetime import UTC, datetime

from wake.adapters import AdapterRegistry
from wake.adapters.context import SessionContext
from wake.types import AgentConfig, ModelConfig


class _NullEvents:
    async def all(self):
        return []
    async def since(self, seq):
        return []
    async def latest(self, type=None):
        return None
    async def count(self):
        return 0


class _NullTools:
    def list(self):
        return []
    def get(self, name):
        raise KeyError(name)
    async def execute(self, name, input, *, tool_use_id):
        raise NotImplementedError


def make_ctx() -> SessionContext:
    now = datetime.now(UTC)
    agent = AgentConfig(
        id="agt_demo",
        name="discovery-demo",
        model=ModelConfig(id="claude-opus-4-7"),
        created_at=now,
        updated_at=now,
    )
    return SessionContext(
        session_id="sess_demo",
        agent_id=agent.id,
        agent_version=agent.version,
        agent_config=agent,
    )


async def main():
    registry = AdapterRegistry()
    registry.discover()
    ctx = make_ctx()

    for name in sorted(registry.names()):
        adapter = registry.get(name)
        events = [ev async for ev in adapter.step(ctx, _NullEvents(), _NullTools())]
        for ev in events:
            text = ev.payload["content"][0]["text"]
            print(f"  {name:<10} → {ev.type}: {text!r}")


asyncio.run(main())
PY

echo
echo "[wake] done — every package on PyPI publishing a 'wake.adapters'"
echo "[wake] entry point is now discoverable to your Wake install."
