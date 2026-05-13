"""Cost tracking — LiteLLM ``success_callback`` → Wake event metadata.

LiteLLM computes per-call cost via its model registry (`response_cost`
in the response) and **also** invokes registered callbacks with the
final kwargs/usage. We hook the callback so every completion's cost
shows up in the ``cost_tracker`` (which the harness later folds into
``assistant.message.metadata.cost_usd``).

The tracker is intentionally a small thread-safe in-process registry —
production deployments swap it for a Redis-backed implementation but
the contract stays identical.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CostMetadata:
    """Per-call cost record returned to the substrate."""

    model: str
    cost_usd: float
    input_tokens: int
    output_tokens: int
    timestamp: datetime
    session_id: str | None = None


@dataclass
class CostTracker:
    """In-process aggregator for cost metadata."""

    _records: list[CostMetadata] = field(default_factory=list)
    _by_session: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, meta: CostMetadata) -> None:
        with self._lock:
            self._records.append(meta)
            if meta.session_id:
                self._by_session[meta.session_id] = (
                    self._by_session.get(meta.session_id, 0.0) + meta.cost_usd
                )
        # Structured log entry. Cost is non-sensitive so we can log freely.
        logger.info(
            "llm_cost_recorded",
            model=meta.model,
            cost_usd=meta.cost_usd,
            input_tokens=meta.input_tokens,
            output_tokens=meta.output_tokens,
            session_id=meta.session_id,
        )

    def all(self) -> list[CostMetadata]:
        with self._lock:
            return list(self._records)

    def total_usd(self) -> float:
        with self._lock:
            return sum(r.cost_usd for r in self._records)

    def session_total_usd(self, session_id: str) -> float:
        with self._lock:
            return float(self._by_session.get(session_id, 0.0))

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
            self._by_session.clear()


_GLOBAL_TRACKER = CostTracker()


def get_tracker() -> CostTracker:
    """Return the process-global cost tracker."""
    return _GLOBAL_TRACKER


def install_litellm_callback(tracker: CostTracker | None = None) -> None:
    """Wire LiteLLM's ``success_callback`` to feed our ``CostTracker``.

    Idempotent — calling twice does not double-register. Safe to invoke
    on module import in a long-running server.

    If LiteLLM is not importable (e.g. unit test isolation), this is a
    silent no-op. Tests that care about the callback wire their own
    fake tracker via ``cost_tracker.record(...)`` directly.
    """
    target = tracker if tracker is not None else _GLOBAL_TRACKER
    try:
        import litellm  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover — litellm is a hard dep
        logger.warning("litellm_not_installed_cost_tracking_disabled")
        return

    def _callback(
        kwargs: dict[str, Any],
        completion_response: Any,
        start_time: Any,
        end_time: Any,
    ) -> None:
        # We deliberately swallow exceptions here — a busted callback
        # must never poison a real completion.
        try:
            model = kwargs.get("model", "")
            # LiteLLM stores cost on the response (preferred) or in
            # kwargs after computing it.
            cost_usd = float(
                getattr(completion_response, "response_cost", None)
                or kwargs.get("response_cost", 0.0)
                or 0.0
            )
            usage_obj = getattr(completion_response, "usage", None)
            if usage_obj is not None and hasattr(usage_obj, "model_dump"):
                usage = usage_obj.model_dump()
            elif isinstance(usage_obj, dict):
                usage = usage_obj
            else:
                usage = {}

            session_id = kwargs.get("metadata", {}).get("session_id") or kwargs.get(
                "session_id"
            )

            now = end_time if isinstance(end_time, datetime) else datetime.utcnow()

            target.record(
                CostMetadata(
                    model=str(model),
                    cost_usd=cost_usd,
                    input_tokens=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
                    output_tokens=int(
                        usage.get("completion_tokens") or usage.get("output_tokens") or 0
                    ),
                    timestamp=now,
                    session_id=session_id,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("cost_tracking_callback_failed")

    # Avoid double-registration. ``litellm.success_callback`` is a list of
    # callables; we tag ours with a sentinel attribute.
    sentinel = "_wake_cost_tracker"
    setattr(_callback, sentinel, True)

    callbacks: list[Any] = getattr(litellm, "success_callback", None) or []
    if not isinstance(callbacks, list):
        callbacks = []
    callbacks = [cb for cb in callbacks if not getattr(cb, sentinel, False)]
    callbacks.append(_callback)
    litellm.success_callback = callbacks


__all__ = [
    "CostMetadata",
    "CostTracker",
    "get_tracker",
    "install_litellm_callback",
]
