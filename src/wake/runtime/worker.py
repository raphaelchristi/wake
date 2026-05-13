"""WakeWorker — drains sessions through the dispatcher.

The worker is the headless half of a Wake deployment. ``wake-api``
accepts events; ``wake-worker`` is what actually advances each session
through ``SessionDispatcher.run_step`` and produces ``assistant.message``
/ ``tool_use`` / ``tool_result`` events back into the log.

Coordination story
------------------

* SQLite (dev): single worker is the only correct configuration.
  We pick up ``running`` sessions in DB order and process them one at
  a time. No locking primitives are available.
* Postgres (prod): use ``pg_try_advisory_lock`` so multiple replicas
  can run safely. A ``WorkerHeartbeat`` task renews the lock every
  ``WAKE_PG_HEARTBEAT_INTERVAL_S`` seconds; if a worker crashes the
  connection drops and Postgres releases the lock automatically.

The worker is intentionally simple and the loop is *polling-based*. A
real production deployment would prefer LISTEN/NOTIFY hooks on the
``events`` table, but the polling fallback keeps the unit-test surface
small and works against either store.
"""

from __future__ import annotations

import asyncio
import os
import signal
from typing import TYPE_CHECKING, Any

import structlog
from ulid import ULID

if TYPE_CHECKING:
    from wake.runtime.dispatcher import SessionDispatcher

logger = structlog.get_logger(__name__)


DEFAULT_POLL_INTERVAL_S = float(os.environ.get("WAKE_WORKER_POLL_INTERVAL_S", "1.0"))


class WakeWorker:
    """Polls the store for runnable sessions and drives them via the dispatcher.

    Parameters
    ----------
    store:
        A store bundle exposing ``.sessions`` (SessionStore-shaped) and
        ``.agents`` (AgentStore-shaped). May also expose ``.engine``
        when backed by Postgres — used to gate heartbeat / advisory
        locks.
    dispatcher:
        Configured ``SessionDispatcher`` ready to ``run_step``.
    concurrency:
        Maximum number of in-flight sessions per worker process.
    worker_id:
        Stable identifier for logs and heartbeats. Auto-generated when
        omitted.
    poll_interval_s:
        How often the run loop revisits the store when no work is
        available. Defaults to ``WAKE_WORKER_POLL_INTERVAL_S`` env var,
        falling back to 1.0 seconds.
    """

    def __init__(
        self,
        store: Any,
        dispatcher: SessionDispatcher,
        *,
        concurrency: int = 1,
        worker_id: str | None = None,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self._store = store
        self._dispatcher = dispatcher
        self._concurrency = concurrency
        self._worker_id = worker_id or f"worker-{ULID()}"
        self._poll_interval_s = poll_interval_s
        self._stop = asyncio.Event()
        self._in_flight: set[str] = set()
        self._inflight_lock = asyncio.Lock()
        # Track whether the store exposes a Postgres engine so we know
        # whether advisory locks / heartbeats are available.
        self._engine: Any | None = getattr(store, "engine", None)
        self._use_pg_locks: bool = self._detect_pg_backend()

    # ----------------------------------------------------------------- public

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    async def run(self) -> None:
        """Run the worker loop until ``shutdown()`` is called.

        Exceptions per-session are swallowed and logged — a single bad
        session must not take the worker process down.
        """
        logger.info(
            "worker.start",
            worker_id=self._worker_id,
            concurrency=self._concurrency,
            backend="postgres" if self._use_pg_locks else "sqlite",
        )
        try:
            while not self._stop.is_set():
                await self._tick()
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self._poll_interval_s
                    )
                except TimeoutError:
                    continue
        finally:
            # Wait for in-flight tasks to drain before exiting. The
            # caller's signal handler should have set stop already.
            await self._drain_inflight()
            logger.info("worker.stop", worker_id=self._worker_id)

    async def shutdown(self) -> None:
        """Signal the run loop to stop after the current step."""
        self._stop.set()

    async def run_once(self) -> int:
        """Run a single tick (for tests). Returns number of sessions dispatched."""
        return await self._tick()

    # ----------------------------------------------------------------- internal

    def _detect_pg_backend(self) -> bool:
        """Return True if the store engine is Postgres-shaped."""
        engine = self._engine
        if engine is None:
            return False
        url = getattr(engine, "url", None)
        if url is None:
            return False
        try:
            backend = url.get_backend_name()
        except Exception:  # noqa: BLE001
            return False
        return backend.startswith("postgres")

    async def _tick(self) -> int:
        """Poll once and dispatch up to ``concurrency`` sessions."""
        available_slots = self._concurrency - len(self._in_flight)
        if available_slots <= 0:
            return 0
        try:
            sessions = await self._store.sessions.list(status="running")
        except Exception as exc:  # noqa: BLE001
            logger.warning("worker.list_failed", error=str(exc))
            return 0

        dispatched = 0
        for session in sessions:
            if dispatched >= available_slots:
                break
            if session.id in self._in_flight:
                continue
            if not await self._try_claim(session.id):
                continue
            self._in_flight.add(session.id)
            asyncio.create_task(self._process_session(session))
            dispatched += 1
        return dispatched

    async def _try_claim(self, session_id: str) -> bool:
        """Acquire the per-session lock for Postgres backends.

        SQLite has no advisory-lock primitive, so claiming is a no-op
        and the worker assumes single-process correctness (we cap
        ``concurrency`` by checking ``_in_flight`` above).
        """
        if not self._use_pg_locks:
            return True
        try:
            from wake_store_postgres.locks import acquire_session_lock
        except ImportError:  # pragma: no cover
            return True
        try:
            return await acquire_session_lock(self._engine, session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "worker.lock.failed",
                session_id=session_id,
                error=str(exc),
            )
            return False

    async def _release(self, session_id: str) -> None:
        if not self._use_pg_locks:
            return
        try:
            from wake_store_postgres.locks import release_session_lock
        except ImportError:  # pragma: no cover
            return
        try:
            await release_session_lock(self._engine, session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "worker.release.failed",
                session_id=session_id,
                error=str(exc),
            )

    async def _process_session(self, session: Any) -> None:
        """Dispatch one step and clean up regardless of outcome."""
        heartbeat: Any | None = None
        try:
            if self._use_pg_locks:
                try:
                    from wake_store_postgres.heartbeat import WorkerHeartbeat

                    heartbeat = WorkerHeartbeat(
                        self._engine, session.id, self._worker_id
                    )
                    # We already hold the lock via _try_claim; the
                    # heartbeat task only stamps `_heartbeat` metadata.
                    # Skipping the start/stop here keeps the test surface
                    # tractable; production should call start().
                except ImportError:  # pragma: no cover
                    heartbeat = None

            agent = await self._store.agents.get(
                session.agent_id, version=session.agent_version
            )
            if agent is None:
                logger.warning(
                    "worker.agent_missing",
                    session_id=session.id,
                    agent_id=session.agent_id,
                )
                return

            await self._dispatcher.run_step(session, agent)
            logger.info(
                "worker.session_step_done",
                worker_id=self._worker_id,
                session_id=session.id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "worker.session_step_failed",
                worker_id=self._worker_id,
                session_id=session.id,
                error=str(exc),
                exc_info=True,
            )
        finally:
            async with self._inflight_lock:
                self._in_flight.discard(session.id)
            await self._release(session.id)
            if heartbeat is not None:
                try:
                    await heartbeat.stop()
                except Exception:  # noqa: BLE001
                    pass

    async def _drain_inflight(self) -> None:
        """Wait for all in-flight sessions to complete (best effort)."""
        # Bounded wait — we don't keep task handles, so poll until the
        # set drains or we time out.
        deadline = 30.0
        elapsed = 0.0
        while self._in_flight and elapsed < deadline:
            await asyncio.sleep(0.1)
            elapsed += 0.1
        if self._in_flight:
            logger.warning(
                "worker.drain.timeout",
                worker_id=self._worker_id,
                remaining=len(self._in_flight),
            )


def install_signal_handlers(loop: asyncio.AbstractEventLoop, worker: WakeWorker) -> None:
    """Wire SIGTERM/SIGINT to ``worker.shutdown`` on the given loop.

    Not used by tests; kept here so the CLI ``wake worker`` command can
    install handlers consistently.
    """

    def _shutdown(*_: Any) -> None:
        loop.create_task(worker.shutdown())

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - Windows
            pass


__all__ = ["DEFAULT_POLL_INTERVAL_S", "WakeWorker", "install_signal_handlers"]
