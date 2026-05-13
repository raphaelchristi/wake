"""HarnessAdapter Protocol v0.1.0.

Authoritative definition of the interface between Wake's runtime and any
harness implementation. See ``docs/SPEC-HARNESS-ADAPTER.md`` for the
narrative spec; this file is the executable contract.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from wake.adapters.context import SessionContext
    from wake.adapters.events import EventStream
    from wake.adapters.tool_registry import ToolRegistry
    from wake.types import Event


LifecycleEvent = Literal["created", "resumed", "interrupted", "terminated"]
"""Notifications about session lifecycle transitions.

- ``created``    — first time the session is wake()'d
- ``resumed``    — wake() after a previous step ended (idle → running again)
- ``interrupted``— user requested interrupt; current step is cancelled
- ``terminated`` — session is moving to the terminated state
"""


@runtime_checkable
class HarnessAdapter(Protocol):
    """A harness that can execute one or more steps of a Wake session.

    Implementations must be stateless across step() calls: the only
    persistent state lives in the event log, exposed via the ``events``
    parameter.

    Each implementation declares:

    - ``name``           — unique identifier (e.g. ``"claude-sdk"``)
    - ``version``        — semver string of the adapter itself
    - ``compatibility``  — semver range of the HarnessAdapter ABI it targets
                           (e.g. ``"wake-harness-adapter@^0.1"``)
    """

    name: str
    version: str
    compatibility: str

    async def step(
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        """Execute one step of reasoning.

        Receives:
            ctx:    session context — agent config, sandbox/vault handles
            events: read-only stream of events already in the session log
            tools:  registry of tools available to this session (already
                    filtered by permission policy)

        Yields:
            new events to be appended to the session log

        Runtime guarantees:
            - ``events`` is the COMPLETE log up to now
            - ``tools`` is the visible set (permission policy applied)
            - emitted events are persisted before the next step sees them
            - ``step()`` may be cancelled (asyncio.CancelledError) — clean up
            - ``step()`` may be re-invoked for the same session — must be
              idempotent (use tool_use_id for dedup of side-effecting tools)

        Adapter guarantees:
            - calls tools EXCLUSIVELY via ``tools.execute(name, input, ...)``;
              must not invoke tool functions directly
            - emitted events follow the canonical schema
              (``docs/SPEC-EVENT-SCHEMA.md``)
            - ``seq`` is assigned by the runtime; adapter omits it
        """
        ...

    async def on_lifecycle(
        self,
        ctx: SessionContext,
        event: LifecycleEvent,
    ) -> None:
        """Optional notification of session lifecycle changes.

        Default implementation is a no-op. Adapters override only if they
        need to initialize/teardown framework state (e.g. compile a
        LangGraph StateGraph, build a CrewAI Crew, close a connection).
        """
        ...
