"""Cost budget enforcement (Phase 7 — gap #7).

Wake honours an OPTIONAL ``agent.metadata["max_cost_usd"]`` budget. The
contract:

1. Adapters emit per-event ``cost_usd`` on ``event.payload`` and/or
   ``event.metadata`` (matches the existing LiteLLM callback shape that
   the metrics aggregator already consumes — see
   :mod:`wake.api.metrics_aggregation`).
2. After every dispatcher step we sum the per-session cost across every
   event in the log. If the running total exceeds the budget we emit an
   ``interrupt`` event with ``reason="cost_budget_exceeded"`` and tip
   the session into ``terminated`` via
   :meth:`wake.core.session.SessionService.interrupt`.
3. Enforcement is REACTIVE, not predictive. We never block ``append`` —
   the next step is what fails. The contract calls this out explicitly:
   *"Cost enforcement is REATIVO (post-step), não preditivo. Overrun
   of 1 step não é dimensional (max 1 LLM call)."*

If ``max_cost_usd`` is missing, malformed, or ``<= 0`` the enforcer is a
no-op. The same applies to events without a ``cost_usd`` field — they
contribute zero to the running total.

Cost is parsed identically to the metrics aggregator so the dashboard
and the enforcer never disagree on the running total. We accept both
``payload.cost_usd`` and ``metadata.cost_usd`` because different adapters
tag them in different places (Anthropic SDK stamps payload; LiteLLM
callbacks stamp metadata).

The ``max_cost_usd`` value lives in ``agent.metadata`` so we don't have
to change the agent schema. Strings and numbers are both accepted —
``agent.metadata`` is ``dict[str, str]`` on the wire so anything from
YAML lands as a string.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from wake.core.event_log import EventLog
    from wake.core.session import SessionService
    from wake.types import AgentConfig, Event

log = structlog.get_logger(__name__)


# Result reason emitted on the ``interrupt`` event so downstream
# consumers (dashboard, audit) can filter on it without parsing free-
# form messages.
COST_BUDGET_REASON = "cost_budget_exceeded"


def parse_budget(agent_metadata: dict[str, Any] | None) -> Decimal | None:
    """Return the ``max_cost_usd`` budget as a :class:`~decimal.Decimal`.

    Returns ``None`` when no budget is configured. Returns ``None`` when
    the configured value is non-numeric or ``<= 0`` — the contract is
    "soft attribute": bad data means "no enforcement", never "crash the
    runtime". Operators see the parse failure via the warning log.
    """
    if not agent_metadata:
        return None
    raw = agent_metadata.get("max_cost_usd")
    if raw is None:
        return None
    try:
        budget = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        log.warning("cost_budget.parse_failed", value=raw)
        return None
    if budget <= 0:
        return None
    return budget


def event_cost(event: Event) -> Decimal:
    """Return the per-event ``cost_usd`` contribution.

    Mirrors :func:`wake.api.metrics_aggregation._coerce_cost` semantics:
    bad data contributes 0 (never raises). We sum payload + metadata so
    the running total matches the dashboard exactly.
    """
    total = Decimal("0")
    for source in (event.payload, event.metadata):
        if not isinstance(source, dict):
            continue
        raw = source.get("cost_usd")
        if raw is None:
            continue
        try:
            total += Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            continue
    return total


async def sum_session_cost(
    event_log: EventLog,
    session_id: str,
    *,
    workspace_id: str | None = None,
) -> Decimal:
    """Sum the per-session cost across every event in the log."""
    events = await event_log.get(session_id, workspace_id=workspace_id)
    total = Decimal("0")
    for ev in events:
        total += event_cost(ev)
    return total


class CostBudgetEnforcer:
    """Post-step check + interrupt trigger for ``agent.metadata.max_cost_usd``.

    Wired by :class:`wake.runtime.dispatcher.SessionDispatcher` after
    every ``run_step``. Keeping the logic in its own class lets unit
    tests exercise it without the full dispatcher.
    """

    def __init__(self, event_log: EventLog, sessions: SessionService) -> None:
        self._events = event_log
        self._sessions = sessions

    async def check(
        self,
        session_id: str,
        agent: AgentConfig,
        *,
        workspace_id: str | None = None,
    ) -> bool:
        """Enforce the budget for ``session_id``.

        Returns ``True`` when the session was interrupted (budget
        exceeded). Returns ``False`` when no action was taken — either
        no budget configured, no spend yet, or spend within budget.

        Idempotent: if the session is already terminated (because a
        previous step already tripped the budget) we don't emit a
        duplicate interrupt event.
        """
        budget = parse_budget(agent.metadata)
        if budget is None:
            return False
        total = await sum_session_cost(
            self._events, session_id, workspace_id=workspace_id
        )
        if total <= budget:
            return False
        log.warning(
            "cost_budget.exceeded",
            session_id=session_id,
            agent_id=agent.id,
            total_usd=str(total),
            budget_usd=str(budget),
        )
        await self._sessions.interrupt(
            session_id,
            reason=COST_BUDGET_REASON,
            workspace_id=workspace_id,
            metadata={
                "total_usd": str(total),
                "budget_usd": str(budget),
                "agent_id": agent.id,
            },
        )
        return True


__all__ = [
    "COST_BUDGET_REASON",
    "CostBudgetEnforcer",
    "event_cost",
    "parse_budget",
    "sum_session_cost",
]
