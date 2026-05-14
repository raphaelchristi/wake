"""Unit tests for ``wake.runtime.canary``.

Covers:

* ``parse_canary_weight`` handles missing / malformed / out-of-range
  values by clamping to ``[0, 100]``.
* ``select_version`` always returns the latest stable when no canary
  exists.
* ``select_version`` always returns the canary when its weight is 100.
* ``select_version`` distribution converges to the canary weight when
  fed a uniform RNG over many trials.
* ``select_for_new_session`` on ``InMemoryAgentStore`` works through
  the default base helper.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from tests.unit.fakes import InMemoryAgentStore
from wake.runtime.canary import (
    CANARY_WEIGHT_KEY,
    NO_CANARY,
    parse_canary_weight,
    select_version,
    split_versions,
)
from wake.types import AgentConfig, ModelConfig


def _agent(version: int, *, canary_weight: str | None = None) -> AgentConfig:
    meta: dict[str, str] = {}
    if canary_weight is not None:
        meta[CANARY_WEIGHT_KEY] = canary_weight
    return AgentConfig(
        id="agent_x",
        name="test",
        model=ModelConfig(id="claude-opus-4-7"),
        metadata=meta,
        version=version,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ----- parse_canary_weight ----------------------------------------------


def test_parse_weight_missing_returns_zero() -> None:
    assert parse_canary_weight(_agent(1)) == NO_CANARY


def test_parse_weight_numeric() -> None:
    assert parse_canary_weight(_agent(1, canary_weight="42")) == 42.0


def test_parse_weight_decimal() -> None:
    assert parse_canary_weight(_agent(1, canary_weight="12.5")) == 12.5


def test_parse_weight_garbage_returns_zero() -> None:
    assert parse_canary_weight(_agent(1, canary_weight="not_a_number")) == 0.0


def test_parse_weight_clamps_to_hundred() -> None:
    assert parse_canary_weight(_agent(1, canary_weight="150")) == 100.0


def test_parse_weight_clamps_negative() -> None:
    assert parse_canary_weight(_agent(1, canary_weight="-5")) == 0.0


def test_parse_weight_whitespace_only_returns_zero() -> None:
    assert parse_canary_weight(_agent(1, canary_weight="   ")) == 0.0


# ----- split_versions ---------------------------------------------------


def test_split_partitions_stable_and_canary() -> None:
    versions = [
        _agent(1),
        _agent(2),
        _agent(3, canary_weight="20"),
        _agent(4),  # stable returned to default
    ]
    stable, canary = split_versions(versions)
    assert [v.version for v in stable] == [1, 2, 4]
    assert [v.version for v in canary] == [3]


# ----- select_version ---------------------------------------------------


def test_select_returns_latest_stable_when_no_canary() -> None:
    versions = [_agent(1), _agent(2), _agent(3)]
    selected = select_version(versions)
    assert selected.version == 3


def test_select_returns_canary_at_full_weight() -> None:
    versions = [_agent(1), _agent(2), _agent(3, canary_weight="100")]
    selected = select_version(versions)
    assert selected.version == 3


def test_select_never_picks_canary_at_zero_weight() -> None:
    """weight=0 means "this version is stable" — both rows are in the
    stable bucket, so latest stable (v2) wins."""
    versions = [_agent(1), _agent(2, canary_weight="0")]
    selected = select_version(versions)
    assert selected.version == 2  # latest stable


def test_select_falls_back_to_stable_when_canary_zero_but_real_canary_exists() -> None:
    """Canary v=0 is treated as stable; a real canary at v=50 above it
    is the one that controls rollout."""
    versions = [
        _agent(1),
        _agent(2, canary_weight="0"),  # promoted away → stable bucket
        _agent(3, canary_weight="100"),  # current canary
    ]
    selected = select_version(versions)
    assert selected.version == 3  # canary at 100%


def test_select_distribution_matches_weight() -> None:
    """30% weight → ~30% canary selection over 10k trials."""
    versions = [_agent(1), _agent(2, canary_weight="30")]
    rng = random.Random(1234)
    canary_hits = 0
    trials = 10_000
    for _ in range(trials):
        if select_version(versions, rng=rng).version == 2:
            canary_hits += 1
    ratio = canary_hits / trials
    # Allow ±3% slop on 10k samples — well within Chernoff bounds for
    # a 30/70 split.
    assert 0.27 <= ratio <= 0.33, f"got {ratio:.3f}; expected ≈0.30"


def test_select_picks_canary_when_only_canary_exists() -> None:
    versions = [_agent(1, canary_weight="50"), _agent(2, canary_weight="80")]
    # All versions are canary → latest wins (admin promoted everything).
    selected = select_version(versions, rng=random.Random(7))
    assert selected.version == 2


def test_select_empty_raises() -> None:
    with pytest.raises(ValueError):
        select_version([])


# ----- AgentStore.select_for_new_session --------------------------------


@pytest.mark.asyncio
async def test_select_for_new_session_default_helper() -> None:
    store = InMemoryAgentStore()
    agent = await store.create(name="x", model=ModelConfig(id="claude-opus-4-7"))
    selected = await store.select_for_new_session(agent.id)
    assert selected is not None
    assert selected.version == 1


@pytest.mark.asyncio
async def test_select_for_new_session_respects_canary() -> None:
    store = InMemoryAgentStore()
    agent = await store.create(name="x", model=ModelConfig(id="claude-opus-4-7"))
    # Update with canary_weight=100 → guaranteed canary version.
    await store.update(
        agent.id,
        metadata={CANARY_WEIGHT_KEY: "100"},
    )
    selected = await store.select_for_new_session(agent.id)
    assert selected is not None
    assert selected.version == 2  # canary version
    assert parse_canary_weight(selected) == 100.0


@pytest.mark.asyncio
async def test_select_for_new_session_unknown_returns_none() -> None:
    store = InMemoryAgentStore()
    out = await store.select_for_new_session("agent_doesnotexist")
    assert out is None
