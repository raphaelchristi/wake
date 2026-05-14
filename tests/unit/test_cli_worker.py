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

from wake.runtime.worker import WakeWorker  # noqa: E402

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


# ---------------------------------------------------------------------------
# Postgres claim semantics (Phase 5.2 regression)
# ---------------------------------------------------------------------------


class _FakeHeartbeat:
    """Stand-in for ``wake_store_postgres.heartbeat.WorkerHeartbeat``.

    Captures start/stop calls so tests can assert the worker actually
    holds the lock for the dispatcher step and releases it after.
    """

    def __init__(self, engine: Any, session_id: str, worker_id: str) -> None:
        self.session_id = session_id
        self.worker_id = worker_id
        self.started = False
        self.stopped = False
        # Track ordering relative to dispatcher.run_step.
        self.events: list[str] = []
        # If set to False, start() returns False (lock contended).
        self.acquire_result = True

    async def start(self) -> bool:
        self.started = True
        self.events.append("start")
        _FakeHeartbeat._global.append(("start", self.session_id))
        return self.acquire_result

    async def stop(self) -> None:
        self.stopped = True
        self.events.append("stop")
        _FakeHeartbeat._global.append(("stop", self.session_id))

    # Class-level recorder used to inspect interleaving across instances.
    _global: list[tuple[str, str]] = []


class _PgFakeEngine:
    """Just enough of an AsyncEngine to look Postgres-shaped to the worker."""

    class _Url:
        def get_backend_name(self) -> str:
            return "postgresql"

    url = _Url()


def _install_fake_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject the FakeHeartbeat as `wake_store_postgres.heartbeat.WorkerHeartbeat`.

    The worker imports lazily inside ``_try_claim``; we wire a module
    stub via ``sys.modules`` so the import succeeds with our double.
    """
    import sys
    import types

    _FakeHeartbeat._global.clear()
    module = types.ModuleType("wake_store_postgres.heartbeat")
    module.WorkerHeartbeat = _FakeHeartbeat  # type: ignore[attr-defined]
    # Make sure the parent package is present too.
    parent = sys.modules.get("wake_store_postgres")
    if parent is None:
        parent = types.ModuleType("wake_store_postgres")
        monkeypatch.setitem(sys.modules, "wake_store_postgres", parent)
    monkeypatch.setitem(sys.modules, "wake_store_postgres.heartbeat", module)


@pytest.mark.asyncio
async def test_worker_holds_lock_during_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Postgres backend: heartbeat.start() runs before dispatch, stop() after.

    Regression for Codex finding: worker claimed a one-off lock that was
    released the moment the helper returned, then never started a
    heartbeat. With the fix the WorkerHeartbeat is the claim handle and
    its lifetime brackets ``dispatcher.run_step``.
    """
    _install_fake_heartbeat(monkeypatch)

    sessions = [_FakeSession("s1")]
    store = _FakeStore(sessions)
    store.engine = _PgFakeEngine()  # type: ignore[attr-defined]

    order: list[str] = []

    class _OrderedDispatcher(_RecordingDispatcher):
        async def run_step(self, session: Any, agent: Any) -> None:
            order.append(f"dispatch:{session.id}")
            await super().run_step(session, agent)

    disp = _OrderedDispatcher(store=store)
    worker = WakeWorker(store, disp, concurrency=1, worker_id="w-pg")  # type: ignore[arg-type]
    # The engine is the source of truth for backend detection; force it
    # since the FakeStore was constructed without one.
    worker._engine = store.engine  # type: ignore[attr-defined]  # noqa: SLF001
    worker._use_pg_locks = True  # noqa: SLF001

    dispatched = await worker.run_once()
    assert dispatched == 1
    # Wait for the scheduled task to finish.
    for _ in range(100):
        if disp.calls:
            break
        await asyncio.sleep(0.01)
    # Drain in-flight before asserting on the global recorder.
    for _ in range(100):
        if not worker._in_flight:  # noqa: SLF001
            break
        await asyncio.sleep(0.01)

    events = _FakeHeartbeat._global
    assert events[0] == ("start", "s1"), "lock must be acquired before dispatch"
    assert events[-1] == ("stop", "s1"), "lock must be released after dispatch"


@pytest.mark.asyncio
async def test_worker_skips_session_when_lock_contended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another worker holds the lock → we must not dispatch."""
    _install_fake_heartbeat(monkeypatch)

    contended = _FakeSession("contended")
    store = _FakeStore([contended])
    store.engine = _PgFakeEngine()  # type: ignore[attr-defined]
    disp = _RecordingDispatcher()
    worker = WakeWorker(store, disp, concurrency=1)  # type: ignore[arg-type]
    worker._engine = store.engine  # type: ignore[attr-defined]  # noqa: SLF001
    worker._use_pg_locks = True  # noqa: SLF001

    # Patch FakeHeartbeat to refuse acquisition.
    original_start = _FakeHeartbeat.start

    async def _contended_start(self: _FakeHeartbeat) -> bool:
        self.acquire_result = False
        return await original_start(self)

    monkeypatch.setattr(_FakeHeartbeat, "start", _contended_start)

    dispatched = await worker.run_once()
    assert dispatched == 0
    assert disp.calls == [], "dispatcher must not run when lock is contended"


@pytest.mark.asyncio
async def test_worker_fails_closed_when_postgres_helper_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Engine is Postgres-shaped but `wake_store_postgres` isn't installed.

    The worker must refuse to dispatch rather than running unlocked —
    silently racing across replicas is exactly the failure mode this
    test guards against.
    """
    import sys

    # Make sure the (possibly real) heartbeat module is not importable.
    monkeypatch.setitem(sys.modules, "wake_store_postgres.heartbeat", None)

    sessions = [_FakeSession("s-pg")]
    store = _FakeStore(sessions)
    store.engine = _PgFakeEngine()  # type: ignore[attr-defined]
    disp = _RecordingDispatcher()
    worker = WakeWorker(store, disp, concurrency=1)  # type: ignore[arg-type]
    worker._engine = store.engine  # type: ignore[attr-defined]  # noqa: SLF001
    worker._use_pg_locks = True  # noqa: SLF001

    dispatched = await worker.run_once()
    assert dispatched == 0
    assert disp.calls == [], "must not dispatch without an advisory-lock primitive"
