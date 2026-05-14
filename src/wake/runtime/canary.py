"""Canary version selection — Phase 8 / Tier 2 gap #12.

Wake stores every ``AgentConfig`` mutation as a new immutable version
(``AgentStore.update`` appends a row). Phase 8 turns that history into a
*deployment lever*: an admin can stamp a single agent version with
``metadata["canary_weight"] = "<0-100>"`` and Wake will route that
percentage of new sessions to the canary version.

The selection is **server-side weighted random**: a session creation
samples once from ``[0.0, 100.0)`` and compares against the canary
weight. If the roll is below the weight the canary version wins;
otherwise we use the latest *non-canary* version (the "stable"
release). No state machine — every session is an independent Bernoulli
trial.

Why not a state machine
-----------------------

Production rollouts (Argo Rollouts, Flagger, etc.) ramp up canaries on
a clock + health gates. Wake's surface is intentionally smaller: the
agent admin owns the weight knob; turning it up to 100 promotes the
canary, turning it to 0 rolls back. We do NOT take ownership of
"is the canary healthy" — that lives in the dashboard's metrics view
and in user-defined alerts.

Determinism note
----------------

The default ``selector`` reads ``random.random()`` so different
processes see different rolls. Tests inject a deterministic
``random.Random`` via the ``rng`` kwarg so the unit suite can pin a
distribution.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Iterable

    from wake.types import AgentConfig

logger = structlog.get_logger(__name__)

#: Metadata key on ``AgentConfig.metadata`` that flags a version as canary
#: and carries its rollout weight (0-100). Stored as str because
#: ``AgentConfig.metadata`` is typed ``dict[str, str]``.
CANARY_WEIGHT_KEY = "canary_weight"

#: Sentinel value returned by ``parse_canary_weight`` when the metadata
#: key is missing OR cannot be parsed. We treat malformed values as
#: 0 (stable) — fail closed.
NO_CANARY: float = 0.0


def parse_canary_weight(agent: AgentConfig) -> float:
    """Return ``agent.metadata['canary_weight']`` clamped to ``[0, 100]``.

    Returns 0.0 when the key is absent, empty, non-numeric, or
    out-of-band. We *clamp* rather than reject: an admin that types
    "150" probably means "100%" and we'd rather route 100% than
    surface a 500 to the API caller.
    """
    raw = (agent.metadata or {}).get(CANARY_WEIGHT_KEY, "").strip()
    if not raw:
        return NO_CANARY
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "canary_weight_unparseable",
            agent_id=agent.id,
            value=raw,
        )
        return NO_CANARY
    return max(0.0, min(100.0, value))


def split_versions(
    versions: Iterable[AgentConfig],
) -> tuple[list[AgentConfig], list[AgentConfig]]:
    """Partition ``versions`` into ``(stable, canary)`` lists.

    Stable = no canary_weight key. Canary = has a non-zero canary_weight.
    Both lists preserve input order (oldest first by the
    ``AgentStore.list_versions`` contract).
    """
    stable: list[AgentConfig] = []
    canary: list[AgentConfig] = []
    for v in versions:
        if parse_canary_weight(v) > 0.0:
            canary.append(v)
        else:
            stable.append(v)
    return stable, canary


def select_version(
    versions: Iterable[AgentConfig],
    *,
    rng: random.Random | None = None,
) -> AgentConfig:
    """Pick a version for a new session given the canary rollout config.

    Selection algorithm:

    1. Split into ``(stable, canary)``. If no canary versions exist,
       return the *latest* stable version.
    2. If only canary versions exist (no stable), return the *latest*
       canary version — admin promoted everything.
    3. Otherwise pick the *latest* canary version, parse its weight
       ``w ∈ [0, 100]`` and roll a single ``random.uniform(0, 100)``.
       Return the canary when ``roll < w``, else the latest stable.

    The single-roll model is intentional: multiple canary versions in
    flight at once is not supported (in practice you should bake them
    into a single canary version). The latest canary wins by mtime.

    Parameters
    ----------
    versions:
        Output of ``AgentStore.list_versions`` — oldest first.
    rng:
        Inject ``random.Random(seed)`` to make tests deterministic.
        Defaults to the module-level :mod:`random` for production.
    """
    versions_list = list(versions)
    if not versions_list:
        raise ValueError("select_version requires at least one version")

    stable, canary = split_versions(versions_list)
    if not canary:
        # No canary configured — always return the latest stable.
        return stable[-1]
    if not stable:
        # All versions are canary (e.g. admin promoted the first one
        # to 100%). Just return the latest canary.
        return canary[-1]

    latest_canary = canary[-1]
    weight = parse_canary_weight(latest_canary)
    if weight <= 0.0:
        return stable[-1]
    if weight >= 100.0:
        return latest_canary

    sampler = rng if rng is not None else random
    roll = sampler.uniform(0.0, 100.0)
    if roll < weight:
        logger.info(
            "canary_selected",
            agent_id=latest_canary.id,
            version=latest_canary.version,
            weight=weight,
            roll=roll,
        )
        return latest_canary
    return stable[-1]


__all__ = [
    "CANARY_WEIGHT_KEY",
    "NO_CANARY",
    "parse_canary_weight",
    "select_version",
    "split_versions",
]
