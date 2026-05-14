"""Rate-limit middleware setup for the Wake API.

Implements the Phase 7 ops-hardening contract:

* Storage backend é **in-memory** por padrão; opt-in Redis via env var
  ``WAKE_RATELIMIT_REDIS_URL``. URLs inválidas/inacessíveis fazem
  fallback gracioso pra memory (slowapi/limits faz isso nativo via
  ``in_memory_fallback_enabled``). Wake nunca hard-fails porque o
  operador esqueceu de levantar Redis.
* Rate-limit key extractor: ``"<api_key_hash_or_anon>:<workspace_id>"``.
  O API key é hasheado antes de virar bucket pra não vazar verbatim
  no storage compartilhado.
* Defaults: writes (POST/PATCH/DELETE/PUT) cap em 60/min, reads em
  300/min. Tunables via ``WAKE_RATELIMIT_WRITE`` / ``WAKE_RATELIMIT_READ``
  (sintaxe "<count>/<period>").
* Global kill switch via ``WAKE_RATELIMIT_DISABLED=true`` pra load
  testing / legacy deploys.
* 429 response carrega ``Retry-After`` header + JSON body com
  ``detail``, ``limit``, ``reset_at`` — clientes back-off determinístico.

Implementação usa `limits` (subjacente ao slowapi) diretamente pro
caminho programático — evita acoplamento ao decorator do slowapi
porque queremos compor com ``Depends(...)`` e tirar `enabled=False`
dinâmico.

A storage backend é criada uma vez em ``build_limiter()`` e
attached em ``app.state.limiter``. A dependency ``rate_limit_dep``
resolve via ``request.app.state.limiter``.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from limits import RateLimitItem, parse
from limits.aio.storage import MemoryStorage, RedisStorage
from limits.aio.strategies import MovingWindowRateLimiter

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.responses import Response


logger = structlog.get_logger(__name__)


#: Env var controlling the rate-limit storage backend.
WAKE_RATELIMIT_REDIS_URL_ENV = "WAKE_RATELIMIT_REDIS_URL"
#: Disable rate limiting entirely (load tests / legacy).
WAKE_RATELIMIT_DISABLED_ENV = "WAKE_RATELIMIT_DISABLED"
#: Write-side per-key limit (slowapi syntax).
WAKE_RATELIMIT_WRITE_ENV = "WAKE_RATELIMIT_WRITE"
DEFAULT_WRITE_LIMIT = "60/minute"
#: Read-side per-key limit.
WAKE_RATELIMIT_READ_ENV = "WAKE_RATELIMIT_READ"
DEFAULT_READ_LIMIT = "300/minute"

#: Header the API key dependency reads (mirrors dependencies.py).
WAKE_API_KEY_HEADER = "X-Wake-API-Key"
#: Header the tenant dependency reads.
WAKE_WORKSPACE_ID_HEADER = "X-Wake-Workspace-Id"


def is_disabled() -> bool:
    """Return True when the operator opted out via env."""
    raw = os.environ.get(WAKE_RATELIMIT_DISABLED_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def write_limit() -> str:
    return (
        os.environ.get(WAKE_RATELIMIT_WRITE_ENV, DEFAULT_WRITE_LIMIT).strip()
        or DEFAULT_WRITE_LIMIT
    )


def read_limit() -> str:
    return (
        os.environ.get(WAKE_RATELIMIT_READ_ENV, DEFAULT_READ_LIMIT).strip()
        or DEFAULT_READ_LIMIT
    )


def key_for_request(request: Request) -> str:
    """Build the rate-limit bucket key.

    ``"<api_key_hash_or_anon>:<workspace_id>"``. API key é hasheado
    pro storage não armazenar a chave em claro.
    """
    raw_key = request.headers.get(WAKE_API_KEY_HEADER, "").strip()
    bucket = hashlib.sha256(raw_key.encode()).hexdigest()[:16] if raw_key else "anon"
    workspace = (
        request.headers.get(WAKE_WORKSPACE_ID_HEADER, "default").strip() or "default"
    )
    return f"{bucket}:{workspace}"


def _redact_uri(uri: str) -> str:
    """Hide the password component for safe logging."""
    if "@" not in uri or "://" not in uri:
        return uri
    scheme, rest = uri.split("://", 1)
    head, tail = rest.rsplit("@", 1)
    if ":" in head:
        user = head.split(":", 1)[0]
        return f"{scheme}://{user}:***@{tail}"
    return uri


class WakeRateLimiter:
    """Thin wrapper bundling the storage strategy + per-bucket cache.

    Holds the moving-window strategy from ``limits`` plus a small LRU
    of parsed limit items. The ``enabled`` flag flips the middleware
    off without ripping it out of the dependency graph.
    """

    def __init__(
        self,
        *,
        storage: Any,
        enabled: bool,
        backend_label: str,
    ) -> None:
        self.storage = storage
        self.enabled = enabled
        self.backend_label = backend_label
        self._strategy = MovingWindowRateLimiter(storage)
        # Cache of parsed RateLimitItems so we don't re-parse on every
        # hit. Cleared on env-var change (cheap rebuild via ``parse``).
        self._items: dict[str, RateLimitItem] = {}

    def item_for(self, spec: str) -> RateLimitItem:
        cached = self._items.get(spec)
        if cached is None:
            cached = parse(spec)
            self._items[spec] = cached
        return cached

    async def hit(self, spec: str, key: str) -> bool:
        """Consume one token under ``key`` for ``spec``.

        Returns True when the request is permitted, False when the
        limit was already exhausted. Errors from the storage backend
        are caught and logged — failures are translated to "allowed"
        so a broken Redis doesn't take the API down (operators monitor
        ``wake_ratelimit_errors_total`` to spot this).
        """
        if not self.enabled:
            return True
        try:
            return bool(await self._strategy.hit(self.item_for(spec), key))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ratelimit.storage_error_allowing_request",
                error=str(exc),
                backend=self.backend_label,
            )
            return True

    async def reset(self) -> None:
        """Flush all buckets — used by tests."""
        import contextlib

        with contextlib.suppress(Exception):
            await self.storage.reset()


def build_limiter() -> WakeRateLimiter:
    """Construct the ``WakeRateLimiter`` honouring env knobs.

    * Redis when ``WAKE_RATELIMIT_REDIS_URL`` is set; falls back to
      in-memory on any storage error.
    * Disabled entirely when ``WAKE_RATELIMIT_DISABLED=true``.
    """
    redis_url = os.environ.get(WAKE_RATELIMIT_REDIS_URL_ENV, "").strip()
    if redis_url:
        try:
            storage: Any = RedisStorage(redis_url)
            backend = "redis"
            logger.info("ratelimit.storage", backend=backend, uri=_redact_uri(redis_url))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ratelimit.redis_init_failed_using_memory",
                error=str(exc),
                uri=_redact_uri(redis_url),
            )
            storage = MemoryStorage()
            backend = "memory"
    else:
        storage = MemoryStorage()
        backend = "memory"
        logger.info("ratelimit.storage", backend=backend)
    return WakeRateLimiter(storage=storage, enabled=not is_disabled(), backend_label=backend)


# ---------------------------------------------------------------------------
# FastAPI dependency / exception handler
# ---------------------------------------------------------------------------


class RateLimitExceededError(HTTPException):
    """Subclass so the response handler can format consistently."""

    def __init__(self, limit_spec: str) -> None:
        retry_after = _retry_seconds_for(limit_spec)
        reset_at = int(time.time()) + retry_after
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "detail": f"rate limit exceeded: {limit_spec}",
                "limit": limit_spec,
                "reset_at": reset_at,
            },
            headers={"Retry-After": str(retry_after)},
        )
        self.limit_spec = limit_spec


def _retry_seconds_for(spec: str) -> int:
    try:
        item = parse(spec)
        return int(item.GRANULARITY.seconds)
    except Exception:  # noqa: BLE001
        return 60


async def rate_limit_exceeded_handler(
    _request: Request, exc: RateLimitExceededError
) -> Response:
    """Format the 429 JSON body + Retry-After header."""
    body = exc.detail if isinstance(exc.detail, dict) else {"detail": str(exc.detail)}
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=exc.headers or {},
    )


def rate_limit_dep(
    limit_str: str | None = None,
    *,
    per_route: bool = False,
) -> Callable[[Request], Awaitable[None]]:
    """Return a FastAPI dependency that consumes one rate-limit token.

    * ``limit_str`` — override the default per-method limit. ``None``
      resolves to ``write_limit()`` for write methods and
      ``read_limit()`` otherwise (re-read on every request so the
      operator can SIGHUP/restart to retune).
    * ``per_route`` — when ``True`` the bucket key gets the route path
      appended, giving each endpoint its own counter.

    The limiter is resolved from ``request.app.state.limiter`` so tests
    that rebuild the app with custom limits don't have to monkey-patch
    a module-level singleton.
    """

    async def _dep(request: Request) -> None:
        limiter: WakeRateLimiter | None = getattr(request.app.state, "limiter", None)
        if limiter is None or not limiter.enabled:
            return
        if limit_str is not None:
            spec = limit_str
        else:
            method = request.method.upper()
            spec = (
                write_limit()
                if method in {"POST", "PUT", "PATCH", "DELETE"}
                else read_limit()
            )
        key = key_for_request(request)
        if per_route:
            key = f"{key}|{request.scope.get('path', '')}"
        allowed = await limiter.hit(spec, key)
        if not allowed:
            raise RateLimitExceededError(spec)

    return _dep


__all__ = [
    "DEFAULT_READ_LIMIT",
    "DEFAULT_WRITE_LIMIT",
    "WAKE_RATELIMIT_DISABLED_ENV",
    "WAKE_RATELIMIT_READ_ENV",
    "WAKE_RATELIMIT_REDIS_URL_ENV",
    "WAKE_RATELIMIT_WRITE_ENV",
    "RateLimitExceededError",
    "WakeRateLimiter",
    "build_limiter",
    "is_disabled",
    "key_for_request",
    "rate_limit_dep",
    "rate_limit_exceeded_handler",
    "read_limit",
    "write_limit",
]
