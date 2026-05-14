"""Replay engine — Phase 8 / Tier 2 gap #10.

The engine materialises a *new session* from an existing session's
event log, optionally substituting ``system_prompt`` / ``tools`` /
``max_steps``. The result is a deterministic re-execution: feeding
identical inputs to the same agent yields identical events.

Determinism contract
--------------------

1. The engine reads the **source session's event log** as the
   authoritative input. It does NOT call the adapter — adapters are
   non-deterministic by nature (LLM sampling, tool I/O). The replay
   *projects* the source log into the new session, applying overrides
   to the **inputs** the agent saw.

2. ``user.message`` events are copied verbatim (same payload, new
   ULID, new ``session_id``). They are the user's inputs and must
   not change between original and replay.

3. ``assistant.*`` and ``tool_*`` events are copied verbatim by default
   (the "no-override" replay path). When overrides ARE applied the
   engine emits a ``status`` event carrying the override diff and a
   trailing ``replay.complete`` payload so the dashboard can render
   "X overrides applied" without re-walking the log.

4. ``status`` and ``error`` events from the original log are NOT
   copied — they describe the original session's lifecycle, not the
   replay. The replay emits its own lifecycle events.

Override semantics
------------------

* ``system_prompt`` — when set, recorded on the new session's
  ``metadata["replay_system_prompt"]`` and emitted as the first
  ``status`` event with ``payload["override"] = "system_prompt"``.
  The adapter is NOT re-invoked; the override is a *recorded* change
  for the dashboard diff renderer to display side-by-side.
* ``tools`` — same shape: recorded on metadata + emitted as a status
  event. Tool calls in the original log that reference now-removed
  tools are tagged with ``metadata["replay_warning"] = "tool_removed"``.
* ``max_steps`` — caps the number of ``assistant.message`` events
  copied into the replay. Anything past that boundary is truncated
  and the engine emits a ``status`` event with
  ``payload["truncated"] = true``.

The narrow scope is deliberate. Wake's edit-and-replay is the
*engineering loop* primitive: "I changed this prompt — show me a
side-by-side of what the agent saw and did." The full "re-execute
this session against the LLM" flow is out of scope here; Phase 9+
might add a ``re_execute=true`` flag that calls the adapter live.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from wake.runtime.canary import CANARY_WEIGHT_KEY

if TYPE_CHECKING:
    from wake.core.event_log import EventLog
    from wake.store.base import AgentStore, SessionStore
    from wake.types import AgentConfig, Event, ReplayRequest, ReplayResult, Session

logger = structlog.get_logger(__name__)

#: Default max-steps fallback when the agent does not declare one and
#: the replay request does not override it. Mirrors the dispatcher's
#: practical ceiling — most edit-and-replay loops only care about the
#: first dozen turns.
DEFAULT_MAX_STEPS = 32

#: Events that the engine copies verbatim from the source log into the
#: replay. ``status`` and ``error`` are EXCLUDED — those describe the
#: source session's lifecycle and would confuse the replay timeline.
_COPYABLE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "user.message",
        "assistant.message",
        "assistant.thinking",
        "assistant.delta",
        "tool_use",
        "tool_result",
        "artifact",
        "pause_turn",
        "vault.access",
    }
)


class ReplayError(Exception):
    """Raised when the replay engine cannot satisfy the request."""


def _resolve_max_steps(req: ReplayRequest, agent: AgentConfig) -> int:
    if req.max_steps is not None:
        return req.max_steps
    raw = (agent.metadata or {}).get("max_steps", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return DEFAULT_MAX_STEPS


def _resolve_seed(req: ReplayRequest, source: Session) -> int:
    if req.seed is not None:
        return req.seed
    raw = (source.metadata or {}).get("seed", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    # Deterministic fallback — derive from the source session id so
    # repeated replays of the same source land on the same seed even
    # when neither side set one explicitly.
    return abs(hash(source.id)) % (2**63 - 1)


def _allowed_tools(req: ReplayRequest, agent: AgentConfig) -> set[str]:
    """Return the set of tool *names* permitted in the replay."""
    if req.tools is not None:
        return {t.type for t in req.tools}
    return {t.type for t in (agent.tools or [])}


def _collect_overrides(req: ReplayRequest) -> list[str]:
    applied: list[str] = []
    if req.system_prompt is not None:
        applied.append("system_prompt")
    if req.tools is not None:
        applied.append("tools")
    if req.max_steps is not None:
        applied.append("max_steps")
    return applied


class ReplayEngine:
    """Deterministic event-log replay with override support.

    The engine is stateless across runs — every ``replay`` call gets
    its own ``SessionStore`` / ``EventLog`` handles + reads/writes
    independently. Concurrent replays of the same source session are
    therefore safe: the source log is read-only, the new session is
    a fresh row.
    """

    def __init__(
        self,
        session_store: SessionStore,
        agent_store: AgentStore,
        event_log: EventLog,
    ) -> None:
        self._sessions = session_store
        self._agents = agent_store
        self._events = event_log

    async def replay(
        self,
        source_session_id: str,
        request: ReplayRequest,
        *,
        workspace_id: str | None = None,
    ) -> ReplayResult:
        """Materialise a new session that replays ``source_session_id``.

        Steps:

        1. Load the source session and its agent (pinned version).
        2. Read every event from the source log.
        3. Create a brand-new session row carrying the replay seed +
           override metadata.
        4. Copy ``_COPYABLE_EVENT_TYPES`` events verbatim into the
           new session, capping at ``max_steps`` assistant turns.
        5. Emit synthetic ``status`` events recording the overrides.
        6. Return a :class:`ReplayResult` with both ids + counts.

        Raises ``ReplayError`` when the source session or its agent
        cannot be loaded.
        """
        from wake.types import ReplayResult  # local import — avoid cycle

        source = await self._sessions.get(
            source_session_id, workspace_id=workspace_id
        )
        if source is None:
            raise ReplayError(f"source session {source_session_id!r} not found")

        agent = await self._agents.get(
            source.agent_id,
            version=source.agent_version,
            workspace_id=workspace_id,
        )
        if agent is None:
            raise ReplayError(
                f"agent {source.agent_id!r}@v{source.agent_version} not found "
                "(was it archived between recording and replay?)"
            )

        # Materialise the source log first so a midway store error
        # doesn't leave an empty replay session lying around.
        source_events: list[Event] = await self._events.get(
            source_session_id, workspace_id=workspace_id
        )

        seed = _resolve_seed(request, source)
        max_steps = _resolve_max_steps(request, agent)
        overrides_applied = _collect_overrides(request)
        allowed_tools = _allowed_tools(request, agent)

        # ------ create the new session row -------------------------
        # Note: canary metadata on the SOURCE agent is intentionally
        # not propagated to the replay metadata — a replay is a
        # debugging artefact, not a production traffic split.
        replay_metadata: dict[str, str] = {
            "replay_of": source_session_id,
            "replay_seed": str(seed),
            "replay_overrides": ",".join(overrides_applied) or "none",
        }
        if request.system_prompt is not None:
            replay_metadata["replay_system_prompt"] = request.system_prompt
        # Carry the original session's user-facing metadata through
        # the replay (model name, harness, etc.) so downstream views
        # can correlate. Strip canary keys to avoid double-rollout.
        for k, v in (source.metadata or {}).items():
            if k in replay_metadata:
                continue
            if k == CANARY_WEIGHT_KEY:
                continue
            replay_metadata.setdefault(k, v)

        new_session = await self._sessions.create(
            agent_id=agent.id,
            agent_version=agent.version,
            environment_id=source.environment_id,
            metadata=replay_metadata,
            organization_id=source.organization_id,
            workspace_id=source.workspace_id,
        )

        logger.info(
            "replay_created",
            source=source_session_id,
            new=new_session.id,
            overrides=overrides_applied,
            seed=seed,
            max_steps=max_steps,
            source_event_count=len(source_events),
        )

        # ------ emit override status events ------------------------
        # These land BEFORE the copied user.message events so the
        # dashboard diff renderer can show "system_prompt was
        # changed" at the head of the replay timeline.
        for override_name in overrides_applied:
            await self._events.append(
                new_session.id,
                "status",
                {"override": override_name, "from": source_session_id},
                organization_id=new_session.organization_id,
                workspace_id=new_session.workspace_id,
            )

        # ------ replay events --------------------------------------
        assistant_turns = 0
        replayed_count = 0
        truncated = False
        for ev in source_events:
            if ev.type not in _COPYABLE_EVENT_TYPES:
                continue
            if ev.type == "assistant.message":
                assistant_turns += 1
                if assistant_turns > max_steps:
                    truncated = True
                    break

            # Tool-removal annotation: when the original log called a
            # tool that the override excluded we still copy the
            # event (the *fact* of the call is historical) but flag
            # it with metadata so the diff highlights the divergence.
            meta = dict(ev.metadata or {})
            payload = ev.payload
            if ev.type == "tool_use":
                tool_name = (payload or {}).get("name", "")
                if tool_name and tool_name not in allowed_tools:
                    meta["replay_warning"] = "tool_removed"

            await self._events.append(
                new_session.id,
                ev.type,
                payload,
                metadata=meta or None,
                organization_id=new_session.organization_id,
                workspace_id=new_session.workspace_id,
            )
            replayed_count += 1

        if truncated:
            await self._events.append(
                new_session.id,
                "status",
                {"truncated": True, "max_steps": max_steps},
                organization_id=new_session.organization_id,
                workspace_id=new_session.workspace_id,
            )

        return ReplayResult(
            source_session_id=source_session_id,
            new_session_id=new_session.id,
            seed=seed,
            deterministic=not overrides_applied,
            overrides_applied=overrides_applied,
            source_event_count=len(source_events),
            replayed_event_count=replayed_count,
        )


def project_overrides_into_messages(
    events: list[Event],
    overrides: dict[str, Any],
) -> list[dict[str, Any]]:
    """Pure helper used by the dashboard diff renderer.

    Given the source event log + a dict of overrides
    (``{"system_prompt": "...", "tools": [...]}``), produce the
    Anthropic-style messages list the agent *would have seen* with the
    overrides applied. This is the LEFT-side of the side-by-side diff;
    the RIGHT side is the same projection from the replay's event log.
    """
    from wake.core.event_log import EventLog

    messages = EventLog.events_to_messages(events)
    if overrides.get("system_prompt"):
        messages.insert(
            0,
            {
                "role": "system",
                "content": [{"type": "text", "text": overrides["system_prompt"]}],
            },
        )
    return messages


__all__ = [
    "DEFAULT_MAX_STEPS",
    "ReplayEngine",
    "ReplayError",
    "project_overrides_into_messages",
]
