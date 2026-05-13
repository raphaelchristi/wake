"""Tests for the pure-Python helpers that don't need a database.

These run even when Docker is unavailable — useful for CI smoke tests.
"""

from __future__ import annotations

from wake_store_postgres._helpers import (
    content_hash,
    new_ulid,
    normalise_dsn,
    to_sync_dsn,
    utcnow,
)
from wake_store_postgres.store import _redact


def test_new_ulid_is_26_chars() -> None:
    u = new_ulid()
    assert isinstance(u, str)
    assert len(u) == 26


def test_utcnow_is_timezone_aware() -> None:
    n = utcnow()
    assert n.tzinfo is not None


def test_content_hash_is_stable() -> None:
    a = content_hash({"x": 1, "y": [2, 3]})
    b = content_hash({"y": [2, 3], "x": 1})
    assert a == b


def test_content_hash_distinguishes_inputs() -> None:
    a = content_hash({"x": 1})
    b = content_hash({"x": 2})
    assert a != b


def test_normalise_dsn_passthrough() -> None:
    assert normalise_dsn("postgresql+asyncpg://u:p@h/d") == "postgresql+asyncpg://u:p@h/d"


def test_normalise_dsn_rewrites_bare_postgresql() -> None:
    assert normalise_dsn("postgresql://u:p@h/d") == "postgresql+asyncpg://u:p@h/d"


def test_normalise_dsn_rewrites_legacy_postgres() -> None:
    assert normalise_dsn("postgres://u:p@h/d") == "postgresql+asyncpg://u:p@h/d"


def test_to_sync_dsn_strips_async_driver() -> None:
    assert to_sync_dsn("postgresql+asyncpg://u:p@h/d") == "postgresql://u:p@h/d"


def test_redact_masks_password() -> None:
    masked = _redact("postgresql+asyncpg://user:supersecret@host:5432/db")
    assert "supersecret" not in masked
    assert "user" in masked
    assert "***" in masked


def test_redact_handles_no_password() -> None:
    masked = _redact("postgresql+asyncpg://user@host/db")
    assert "user" in masked


def test_redact_handles_malformed() -> None:
    masked = _redact("not a url at all")
    assert masked == "***"
