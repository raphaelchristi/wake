"""Internal helpers — DSN normalisation, content hashing, ULID minting."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from ulid import ULID


def new_ulid() -> str:
    """Return a freshly minted ULID as a 26-char Crockford-base32 string."""
    return str(ULID())


def utcnow() -> datetime:
    """Return ``datetime.now`` as a UTC-aware datetime.

    Postgres stores timestamps with timezone, so we keep aware datetimes
    end-to-end (unlike the SQLite store which strips tzinfo for storage
    compatibility).
    """
    return datetime.now(UTC)


def content_hash(payload: dict[str, Any]) -> str:
    """Stable SHA-256 over a JSON-canonical encoding of ``payload``.

    Used by ``PostgresAgentStore`` to detect no-op updates — identical to
    the algorithm used by the SQLite reference store.
    """
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def normalise_dsn(dsn: str) -> str:
    """Rewrite a bare ``postgresql://`` URL to use the asyncpg driver.

    The Postgres store uses ``sqlalchemy.ext.asyncio`` which requires a
    driver prefix. We accept both forms for ergonomic configuration:

    * ``postgresql+asyncpg://...`` — pass through
    * ``postgresql://...``         — rewritten to asyncpg
    * ``postgres://...``           — legacy alias; rewritten to asyncpg
    """
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn
    if dsn.startswith("postgresql://"):
        return "postgresql+asyncpg://" + dsn[len("postgresql://") :]
    if dsn.startswith("postgres://"):
        return "postgresql+asyncpg://" + dsn[len("postgres://") :]
    return dsn


def to_sync_dsn(dsn: str) -> str:
    """Convert an asyncpg DSN to the sync form used by Alembic.

    Alembic's migration runner needs a synchronous engine because the
    Alembic API is sync (you can run async migrations but it requires
    boilerplate that adds no value to ``upgrade``).
    """
    if dsn.startswith("postgresql+asyncpg://"):
        return "postgresql://" + dsn[len("postgresql+asyncpg://") :]
    return dsn


__all__ = [
    "new_ulid",
    "utcnow",
    "content_hash",
    "normalise_dsn",
    "to_sync_dsn",
]
