"""Stateless signed OAuth ``state`` tokens (HMAC-SHA256).

Phase 5.1 fix for finding #4: the previous implementation stored OAuth
``state`` in an in-process dict (``AppState.oauth_flows``), so when the
API ran with ``replicas > 1`` (Helm default) a callback could land on a
different pod from the one that issued the state and fail with
``unknown or expired state``.

The replacement is stateless: ``sign_state(payload, secret)`` returns an
opaque token shaped like ``{base64url(json(payload))}.{base64url(hmac)}``
embedding ``iat`` (issued at) + ``exp`` (expiry) timestamps. Every
replica that shares the same ``WAKE_OAUTH_STATE_SECRET`` can verify the
token without coordinating state.

Threat model: the token is a CSRF nonce (per RFC 6749 §10.12). Carrying
``provider``, ``scopes``, ``redirect_uri`` and an optional
``vault_id_to_rotate`` inside it lets the callback handler know what to
do without per-process state. The HMAC prevents tampering; ``exp`` (10
minutes by default) caps the replay window.

Secret resolution:

* ``WAKE_OAUTH_STATE_SECRET`` env → used verbatim.
* Absent → a random 32-byte URL-safe secret is generated at import time
  and logged with a warning telling the operator to set the env for
  multi-replica deploys. In-flight tokens issued before a process
  restart will expire within ``ttl_seconds`` (default 10 min), which is
  acceptable for an OAuth callback.

This module does not depend on any wake internals so it stays importable
from tests with zero ceremony.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


#: Default token TTL — OAuth Authorization Code flows complete in well
#: under this. RFC 6749 §10.12 calls 10 min "generous"; we agree.
DEFAULT_TTL_SECONDS = 600

#: Env var name read by ``_get_secret``.
SECRET_ENV = "WAKE_OAUTH_STATE_SECRET"

# Module-level cache for the resolved secret. Lazy so that tests can
# monkeypatch the env *before* the first sign/verify call.
_cached_secret: str | None = None


class OAuthStateError(ValueError):
    """Raised when a state token is malformed, tampered, or expired."""


# ---------------------------------------------------------------------------
# base64url helpers (no padding, RFC 4648 §5)
# ---------------------------------------------------------------------------


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    # Re-pad so ``urlsafe_b64decode`` accepts it.
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


# ---------------------------------------------------------------------------
# Secret resolution
# ---------------------------------------------------------------------------


def _get_secret() -> str:
    """Return the active signing secret, generating one if needed.

    Cached at module level so successive calls don't re-emit the
    "secret_generated" warning. Tests can override the secret by setting
    the env var **before** the first sign/verify call, or by passing an
    explicit ``secret`` to ``sign_state``/``verify_state``.
    """
    global _cached_secret
    if _cached_secret is not None:
        return _cached_secret

    env = os.environ.get(SECRET_ENV, "").strip()
    if env:
        _cached_secret = env
        return _cached_secret

    # Auto-generate — single-process safe, multi-replica NOT safe.
    _cached_secret = secrets.token_urlsafe(32)
    logger.warning(
        "wake_oauth_state_secret_generated",
        note=(
            f"set {SECRET_ENV} for multi-replica deploys; in-flight "
            "OAuth states will not survive a restart"
        ),
    )
    return _cached_secret


def _reset_secret_cache() -> None:
    """Test hook: clear the cached secret so the env is re-read."""
    global _cached_secret
    _cached_secret = None


# ---------------------------------------------------------------------------
# Sign / verify
# ---------------------------------------------------------------------------


def sign_state(
    payload: dict[str, Any],
    secret: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    """Encode ``payload`` as a signed token of the form ``blob.sig``.

    ``payload`` is JSON-serialised after ``iat`` / ``exp`` are stamped
    onto it, then base64url-encoded. The ``sig`` half is the HMAC-SHA256
    of that base64url string under ``secret`` (or the module's resolved
    secret if ``None``).

    The result is URL-safe and fits comfortably in an OAuth ``state``
    query parameter.
    """
    secret = secret if secret is not None else _get_secret()
    now = int(time.time())
    enriched = dict(payload)
    enriched["iat"] = now
    enriched["exp"] = now + ttl_seconds

    blob_bytes = json.dumps(enriched, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    blob = _b64url_encode(blob_bytes)
    sig = hmac.new(secret.encode("utf-8"), blob.encode("ascii"), hashlib.sha256).digest()
    return f"{blob}.{_b64url_encode(sig)}"


def verify_state(token: str, secret: str | None = None) -> dict[str, Any]:
    """Validate ``token`` and return the decoded payload.

    Raises ``OAuthStateError`` if:

    * the token is structurally invalid (missing dot, undecodable);
    * the HMAC does not match (tampering or wrong secret);
    * ``exp`` is in the past.
    """
    secret = secret if secret is not None else _get_secret()

    if not isinstance(token, str) or "." not in token:
        raise OAuthStateError("malformed state: missing separator")

    blob, sig_b64 = token.rsplit(".", 1)
    if not blob or not sig_b64:
        raise OAuthStateError("malformed state: empty segment")

    try:
        provided_sig = _b64url_decode(sig_b64)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise OAuthStateError("malformed state: undecodable signature") from exc

    expected_sig = hmac.new(
        secret.encode("utf-8"), blob.encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise OAuthStateError("invalid state: signature mismatch")

    try:
        payload_bytes = _b64url_decode(blob)
        decoded = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise OAuthStateError("malformed state: undecodable payload") from exc

    if not isinstance(decoded, dict):
        raise OAuthStateError("malformed state: payload is not an object")

    exp = decoded.get("exp")
    if not isinstance(exp, int):
        raise OAuthStateError("malformed state: missing or non-integer exp")
    if exp <= int(time.time()):
        raise OAuthStateError("expired state")

    return decoded


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "OAuthStateError",
    "SECRET_ENV",
    "sign_state",
    "verify_state",
]
