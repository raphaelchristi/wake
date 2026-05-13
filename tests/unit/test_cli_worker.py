"""Tests for ``wake.runtime.worker.WakeWorker``.

These mock the store + dispatcher; the real Postgres advisory-lock path
is exercised by ``adapters/postgres-store/tests``. The tests here verify
the in-memory scheduling logic: tick semantics, claim/release plumbing,
shutdown handling, and per-process concurrency.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from wake.runtime.worker import WakeWorker


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(
        self,
        sid: str,
        agent_id: str = "agent-1",
        agent_version: int = 1,
        status: str = "running",
    ) -> None:
        self.id = sid
        self.agent_id = agent_id
        self.agent_version = agent_version
        self.status = status


class _FakeAgent:
    def __init__(self, aid: str = "agent-1") -> None:
        self.id = aid
        self.version = 1
        # Empty metadata keeps the dispatcher path lightweight.
        self.metadata: dict[str, str] = {}


class _FakeSessions:
    def __init__(self, sessions: list[_FakeSession]) -> None:
        self._sessions = list(sessions)

    async def list(self, *, status: str | None = None) -> list[_FakeSession]:
        if status is None:
            return list(self._sessions)
        return [s for s in self._sessions if s.status == status]


class _FakeAgents:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._agents = agents

    async def get(self, aid: str, version: int | None = None) -> _FakeAgent | None:
        return self._agents.get(aid)


class _FakeStore:
    def __init__(
        self,
        sessions: list[_FakeSession],
        agents: dict[str, _FakeAgent] | None = None,
    ) -> None:
        self.sessions = _FakeSessions(sessions)
        self.agents = _FakeAgents(
            agents
            if agents is not None
            else {s.agent_id: _FakeAgent(s.agent_id) for s in sessions}
        )
        # No engine attribute — worker treats this as the SQLite path.


class _RecordingDispatcher:
    """Captures calls to ``run_step`` so tests can introspect behaviour.

    When ``store`` is provided the dispatcher also flips the session's
    status to ``"idle"`` once the step completes — mirroring the real
    dispatcher which advances the state machine and prevents the worker
    from re-dispatching the same session forever.
    """

    def __init__(
        self,
        *,
        sleep: float = 0.0,
        raise_on: set[str] | None = None,
        store: _FakeStore | None = None,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self._sleep = sleep
        self._raise_on = raise_on or set()
        self._store = store

    async def run_step(self, session: Any, agent: Any) -> None:
        self.calls.append((session.id, agent.id))
        if session.id in self._raise_on:
            raise RuntimeError(f"boom-{session.id}")
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._store is not None:
            session.status = "idle"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_processes_session() -> None:
    """A single tick dispatches the available running session."""
    sessions = [_FakeSession("s1")]
    store = _FakeStore(sessions)
    disp = _RecordingDispatcher()
    worker = WakeWorker(store, disp, concurrency=1, worker_id="w-test")  # type: ignore[arg-type]

    dispatched = await worker.run_once()
    # Wait for the scheduled task to finish.
    for _ in range(50):
        if disp.calls:
            break
        await asyncio.sleep(0.01)

    assert dispatched == 1
    assert disp.calls == [("s1", "agent-1")]


@pytest.mark.asyncio
async def test_worker_handles_shutdown_signal() -> None:
    """`shutdown()` causes `run()` to return without hanging."""
    store = _FakeStore([])
    disp = _RecordingDispatcher()
    worker = WakeWorker(store, disp, concurrency=1, poll_interval_s=0.05)  # type: ignore[arg-type]

    task = asyncio.create_task(worker.run())
    # Let one tick happen.
    await asyncio.sleep(0.1)
    await worker.shutdown()
    # The run loop must terminate within a short window.
    await asyncio.wait_for(task, timeout=2.0)
    assert worker.stopped is True


@pytest.mark.asyncio
async def test_worker_concurrency_runs_n_sessions_parallel() -> None:
    """With concurrency=N, N sessions kick off on the same tick."""
    sessions = [_FakeSession(f"s{i}") for i in range(4)]
    store = _FakeStore(sessions)
    # Each step blocks briefly so we can observe parallelism.
    disp = _RecordingDispatcher(sleep=0.1, store=store)
    worker = WakeWorker(store, disp, concurrency=3)  # type: ignore[arg-type]

    dispatched = await worker.run_once()
    # Worker scheduled 3 sessions; the 4th must wait until a slot frees.
    assert dispatched == 3
    # Let the scheduled tasks start.
    for _ in range(50):
        if len(disp.calls) >= 3:
            break
        await asyncio.sleep(0.01)
    assert len(disp.calls) == 3
    # While they are still running, the 4th must remain unstarted.
    sids = {sid for sid, _ in disp.calls}
    assert "s3" not in sids
    # Wait for in-flight sessions to settle so the next tick is fair.
    for _ in range(50):
        if len(worker._in_flight) == 0:  # noqa: SLF001 - direct inspection in tests
            break
        await asyncio.sleep(0.02)
    # Next tick should pick up the leftover session.
    leftover = await worker.run_once()
    assert leftover == 1


@pytest.mark.asyncio
async def test_worker_skips_sessions_already_in_flight() -> None:
    """A second tick must not redispatch a session that's still running."""
    sessions = [_FakeSession("s1")]
    store = _FakeStore(sessions)
    disp = _RecordingDispatcher(sleep=0.2)
    worker = WakeWorker(store, disp, concurrency=2)  # type: ignore[arg-type]

    await worker.run_once()
    # Immediately tick again before the first one finishes.
    second = await worker.run_once()
    assert second == 0, "session already in flight must not be re-dispatched"


@pytest.mark.asyncio
async def test_worker_survives_session_failure() -> None:
    """A failing step must not crash the worker."""
    sessions = [_FakeSession("bad"), _FakeSession("good")]
    store = _FakeStore(sessions)
    disp = _RecordingDispatcher(raise_on={"bad"})
    worker = WakeWorker(store, disp, concurrency=2)  # type: ignore[arg-type]

    await worker.run_once()
    for _ in range(50):
        if len(disp.calls) >= 2:
            break
        await asyncio.sleep(0.01)
    # Both sessions are attempted, even though "bad" raises.
    sids = {sid for sid, _ in disp.calls}
    assert sids == {"bad", "good"}
    # Worker is still alive.
    assert worker.stopped is False


@pytest.mark.asyncio
async def test_worker_rejects_invalid_concurrency() -> None:
    store = _FakeStore([])
    disp = _RecordingDispatcher()
    with pytest.raises(ValueError):
        WakeWorker(store, disp, concurrency=0)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_worker_default_worker_id_is_ulid_prefixed() -> None:
    store = _FakeStore([])
    disp = _RecordingDispatcher()
    worker = WakeWorker(store, disp)  # type: ignore[arg-type]
    assert worker.worker_id.startswith("worker-")
