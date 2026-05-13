# ruff: noqa: B008, BLE001
"""Vault routes — drive the dashboard ``/vault`` page.

The dashboard never holds raw credentials. These routes return only
*metadata* (``CredentialMetadata``-shaped dicts) and audit entries. The
actual secret values live in the configured ``VaultAdapter`` (currently
``wake_vault_infisical.InfisicalVault``) and never traverse this layer.

Endpoints (all under ``/v1/vault``):

* ``GET    /vault/credentials``             — list metadata
* ``POST   /vault/oauth/start``             — kick off OAuth (returns auth_url + state)
* ``GET    /vault/oauth/callback``          — exchange code → token → vault.add
* ``POST   /vault/credentials/{id}/rotate`` — start a rotation OAuth flow
* ``DELETE /vault/credentials/{id}``        — revoke
* ``GET    /vault/audit``                   — list recent vault accesses

When no vault is wired (``state.vault is None``) every route returns
``503 Vault not configured``. We deliberately do **not** return 500 so
the dashboard can render an "offline" empty state without confusing it
for a backend panic.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from wake.api.dependencies import AppState, get_state, get_vault
from wake.api.oauth_state import OAuthStateError, sign_state, verify_state

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/vault", tags=["vault"])


SUPPORTED_PROVIDERS = ("github", "slack", "notion", "custom")


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class OAuthStartRequest(BaseModel):
    provider: str
    scopes: list[str] | None = None
    redirect_uri: str | None = Field(
        default=None,
        description=(
            "Override redirect URI. Defaults to the value of "
            "WAKE_OAUTH_<PROVIDER>_REDIRECT_URI env var, or "
            "http://localhost:3000/oauth/callback."
        ),
    )


class OAuthStartResponse(BaseModel):
    provider: str
    auth_url: str
    state: str


class CredentialMetadataDTO(BaseModel):
    vault_id: str
    name: str
    provider: str
    scopes: list[str] = Field(default_factory=list)
    created_at: datetime
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CredentialList(BaseModel):
    data: list[CredentialMetadataDTO]


class AuditEntry(BaseModel):
    timestamp: datetime
    session_id: str | None = None
    provider: str | None = None
    host: str | None = None
    decision: str
    vault_id: str | None = None
    detail: str | None = None


class AuditList(BaseModel):
    data: list[AuditEntry]


class RotateRequest(BaseModel):
    redirect_uri: str | None = None


# ---------------------------------------------------------------------------
# Credentials list
# ---------------------------------------------------------------------------


@router.get("/credentials", response_model=CredentialList)
async def list_credentials(vault: Any = Depends(get_vault)) -> CredentialList:
    """Return all credential metadata. Tokens are never included."""
    try:
        items = await vault.list()
    except Exception as exc:
        logger.exception("vault_list_failed")
        raise HTTPException(status_code=502, detail=f"vault list failed: {exc}") from exc

    return CredentialList(
        data=[
            CredentialMetadataDTO(
                vault_id=getattr(item, "vault_id", ""),
                name=getattr(item, "name", ""),
                provider=str(getattr(item, "provider", "custom")),
                scopes=list(getattr(item, "scopes", []) or []),
                created_at=getattr(item, "created_at", datetime.now(timezone.utc)),
                expires_at=getattr(item, "expires_at", None),
                metadata={
                    k: v
                    for k, v in (getattr(item, "metadata", {}) or {}).items()
                    if k != "access_token"
                },
            )
            for item in items
        ]
    )


# ---------------------------------------------------------------------------
# OAuth start
# ---------------------------------------------------------------------------


def _oauth_config(state: AppState, provider: str) -> dict[str, str]:
    """Resolve OAuth client config for ``provider`` from state + env."""
    cfg = dict(state.oauth_clients.get(provider, {}))
    upper = provider.upper()
    cfg.setdefault("client_id", os.environ.get(f"WAKE_OAUTH_{upper}_CLIENT_ID", ""))
    cfg.setdefault(
        "client_secret",
        os.environ.get(f"WAKE_OAUTH_{upper}_CLIENT_SECRET", ""),
    )
    cfg.setdefault(
        "redirect_uri",
        os.environ.get(
            f"WAKE_OAUTH_{upper}_REDIRECT_URI",
            "http://localhost:3000/oauth/callback",
        ),
    )
    return cfg


async def _start_oauth_flow(
    *,
    app_state: AppState,
    provider: str,
    scopes: list[str] | None,
    redirect_uri: str | None,
    vault_id_to_rotate: str | None = None,
) -> OAuthStartResponse:
    """Internal helper: build authorize URL with a signed ``state`` token.

    Used by both ``POST /oauth/start`` and ``POST /credentials/{id}/rotate``.
    The signed state carries ``provider`` + ``redirect_uri`` + optional
    ``vault_id_to_rotate`` so the callback can complete without any
    per-process map (fix for finding #4).
    """
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown provider {provider!r}; expected one of {SUPPORTED_PROVIDERS}",
        )

    try:
        from wake_vault_infisical.oauth import OAuthFlow  # noqa: PLC0415
    except ImportError as exc:
        raise HTTPException(
            status_code=501, detail="OAuth helper not available"
        ) from exc

    cfg = _oauth_config(app_state, provider)
    if redirect_uri:
        cfg["redirect_uri"] = redirect_uri
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise HTTPException(
            status_code=500,
            detail=(
                f"OAuth client not configured for {provider!r} — set "
                f"WAKE_OAUTH_{provider.upper()}_CLIENT_ID and "
                f"WAKE_OAUTH_{provider.upper()}_CLIENT_SECRET."
            ),
        )

    # Pre-sign a signed state token; pass it to OAuthFlow.build_authorize_url
    # so it lands in the authorize URL verbatim. On callback the provider
    # echoes it back as ``?state=`` and we verify it without server state.
    state_payload: dict[str, Any] = {
        "provider": provider,
        "scopes": list(scopes or []),
        "redirect_uri": cfg["redirect_uri"],
    }
    if vault_id_to_rotate:
        state_payload["vault_id_to_rotate"] = vault_id_to_rotate
    signed = sign_state(state_payload)

    flow = OAuthFlow.for_provider(
        provider,
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        redirect_uri=cfg["redirect_uri"],
    )
    url, returned_state = flow.build_authorize_url(scopes=scopes, state=signed)

    _audit(app_state, decision="oauth_start", provider=provider)

    return OAuthStartResponse(provider=provider, auth_url=url, state=returned_state)


@router.post("/oauth/start", response_model=OAuthStartResponse)
async def oauth_start(
    body: OAuthStartRequest,
    request: Request,
    vault: Any = Depends(get_vault),  # noqa: ARG001 - 503 if vault missing
) -> OAuthStartResponse:
    """Start an OAuth Authorization Code flow for ``body.provider``.

    Returns ``{auth_url, state}`` where ``state`` is a signed token
    (HMAC-SHA256) instead of an opaque server-side handle. Multi-replica
    deploys can complete the callback on any pod that shares
    ``WAKE_OAUTH_STATE_SECRET``.
    """
    app_state = get_state(request)
    return await _start_oauth_flow(
        app_state=app_state,
        provider=body.provider,
        scopes=body.scopes,
        redirect_uri=body.redirect_uri,
    )


# ---------------------------------------------------------------------------
# OAuth callback
# ---------------------------------------------------------------------------


@router.get("/oauth/callback", response_model=CredentialMetadataDTO)
async def oauth_callback(
    request: Request,
    code: str = Query(..., description="Authorization code from the provider"),
    state: str = Query(..., description="Signed state echoed by the provider"),
    vault: Any = Depends(get_vault),
) -> CredentialMetadataDTO:
    """Exchange an OAuth ``code`` for an access token, then store it.

    The ``state`` is now a signed HMAC-SHA256 token (Phase 5.1 finding #4
    fix) — any replica that shares ``WAKE_OAUTH_STATE_SECRET`` can verify
    it. If the decoded payload carries ``vault_id_to_rotate`` we route to
    ``vault.replace`` (rotate); otherwise ``vault.add`` (initial add).
    """
    app_state = get_state(request)

    try:
        decoded = verify_state(state)
    except OAuthStateError as exc:
        _audit(app_state, decision="oauth_failed", detail=f"state: {exc}")
        # Be explicit about what went wrong so old clients holding pre-5.1
        # opaque-UUID states see a clear error instead of an empty 400.
        raise HTTPException(
            status_code=400,
            detail=f"invalid or expired OAuth state: {exc}",
        ) from exc

    provider = str(decoded.get("provider", "custom"))
    scopes = list(decoded.get("scopes", []) or [])
    redirect_uri = str(decoded.get("redirect_uri", ""))
    vault_id_to_rotate = decoded.get("vault_id_to_rotate")
    if vault_id_to_rotate is not None and not isinstance(vault_id_to_rotate, str):
        raise HTTPException(
            status_code=400, detail="invalid state: vault_id_to_rotate must be str"
        )

    # Rebuild the flow from env-resolved config. Multi-replica safe: every
    # replica reads the same client_id/secret/redirect_uri from env.
    cfg = _oauth_config(app_state, provider)
    if redirect_uri:
        cfg["redirect_uri"] = redirect_uri
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise HTTPException(
            status_code=500,
            detail=(
                f"OAuth client not configured for {provider!r}; the callback "
                "pod must share WAKE_OAUTH_<PROVIDER>_CLIENT_ID/SECRET env."
            ),
        )

    try:
        from wake_vault_infisical.oauth import OAuthFlow  # noqa: PLC0415
    except ImportError as exc:
        raise HTTPException(
            status_code=501, detail="OAuth helper not available"
        ) from exc

    flow = OAuthFlow.for_provider(
        provider,
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        redirect_uri=cfg["redirect_uri"],
    )
    # The flow's own CSRF check is satisfied by passing ``state`` through
    # (it only compares if _state was latched on this instance; we did NOT
    # call build_authorize_url here so the check is skipped).
    try:
        data = await flow.exchange_code(code, state=state)
    except Exception as exc:
        logger.exception("oauth_callback_failed", provider=provider)
        _audit(app_state, decision="oauth_failed", provider=provider, detail=str(exc))
        raise HTTPException(status_code=400, detail=f"OAuth exchange failed: {exc}") from exc

    token: str = str(data.get("access_token", ""))
    if not token:
        raise HTTPException(status_code=502, detail="provider returned empty token")

    if vault_id_to_rotate:
        # Rotate: replace the existing credential (carry over name/provider/scopes
        # from the old entry unless we have a tighter spec). Falls back to
        # ``vault.add`` when the adapter does not implement ``replace`` so old
        # adapters don't hard-fail.
        try:
            if hasattr(vault, "replace"):
                meta = await vault.replace(
                    vault_id_to_rotate,
                    value=token,
                    provider=provider,
                    scopes=scopes or None,
                    metadata={"oauth_source": "dashboard", "rotated": True},
                )
            else:
                # Defensive: degrade to add + best-effort revoke.
                name = (
                    f"{provider}_token_"
                    f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
                )
                meta = await vault.add(
                    name=name,
                    provider=provider,
                    value=token,
                    scopes=scopes or None,
                    metadata={"oauth_source": "dashboard", "rotated": True},
                )
                try:
                    await vault.revoke(vault_id_to_rotate)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "vault_legacy_revoke_after_rotate_failed",
                        vault_id=vault_id_to_rotate,
                    )
        except Exception as exc:
            logger.exception("vault_replace_failed", provider=provider)
            raise HTTPException(
                status_code=502, detail=f"vault replace failed: {exc}"
            ) from exc

        _audit(
            app_state,
            decision="rotated",
            provider=provider,
            vault_id=getattr(meta, "vault_id", None),
            detail=f"rotated_from={vault_id_to_rotate}",
        )
    else:
        name = f"{provider}_token_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        try:
            meta = await vault.add(
                name=name,
                provider=provider,
                value=token,
                scopes=scopes or None,
                metadata={"oauth_source": "dashboard"},
            )
        except Exception as exc:
            logger.exception("vault_add_failed", provider=provider)
            raise HTTPException(status_code=502, detail=f"vault add failed: {exc}") from exc

        _audit(
            app_state,
            decision="oauth_success",
            provider=provider,
            vault_id=getattr(meta, "vault_id", None),
        )

    return CredentialMetadataDTO(
        vault_id=getattr(meta, "vault_id", ""),
        name=getattr(meta, "name", ""),
        provider=str(getattr(meta, "provider", provider)),
        scopes=list(getattr(meta, "scopes", []) or []),
        created_at=getattr(meta, "created_at", datetime.now(timezone.utc)),
        expires_at=getattr(meta, "expires_at", None),
        metadata={
            k: v
            for k, v in (getattr(meta, "metadata", {}) or {}).items()
            if k != "access_token"
        },
    )


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


@router.post(
    "/credentials/{vault_id}/rotate",
    response_model=OAuthStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rotate_credential(
    vault_id: str,
    body: RotateRequest,
    request: Request,
    vault: Any = Depends(get_vault),
) -> OAuthStartResponse:
    """Start a new OAuth flow that will *replace* ``vault_id`` on callback.

    Two-step rotate: this endpoint returns an auth URL whose ``state``
    embeds the original ``vault_id``. When the user finishes the flow
    the callback handler calls ``vault.replace(vault_id, new_token)``
    (Phase 5.1 finding #5 fix). The old credential is revoked atomically
    inside ``replace``, so there is no need for the operator to also
    issue a ``DELETE`` afterwards.
    """
    try:
        meta = await vault.get_metadata(vault_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"credential not found: {exc}") from exc

    provider = str(getattr(meta, "provider", "custom"))
    scopes = list(getattr(meta, "scopes", []) or [])

    app_state = get_state(request)
    start_resp = await _start_oauth_flow(
        app_state=app_state,
        provider=provider,
        scopes=scopes,
        redirect_uri=body.redirect_uri,
        vault_id_to_rotate=vault_id,
    )

    _audit(
        app_state,
        decision="rotate_started",
        provider=provider,
        vault_id=vault_id,
    )
    return start_resp


# ---------------------------------------------------------------------------
# Revoke
# ---------------------------------------------------------------------------


@router.delete(
    "/credentials/{vault_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_credential(
    vault_id: str,
    request: Request,
    vault: Any = Depends(get_vault),
) -> None:
    """Revoke a vault credential. Idempotent (404 is swallowed)."""
    try:
        await vault.revoke(vault_id)
    except Exception as exc:
        # Idempotent revoke — VaultAdapter.revoke contract says no error
        # on missing IDs. Defensive: surface 502 if the vault itself is sick.
        logger.warning("vault_revoke_failed", vault_id=vault_id, error=str(exc))
        raise HTTPException(status_code=502, detail=f"vault revoke failed: {exc}") from exc

    _audit(
        get_state(request),
        decision="revoked",
        vault_id=vault_id,
    )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


@router.get("/audit", response_model=AuditList)
async def list_audit(
    request: Request,
    since: datetime | None = Query(None, description="Only return entries after this ISO ts"),
    limit: int = Query(100, ge=1, le=1000),
    provider: str | None = Query(None),
    host: str | None = Query(None),
    decision: str | None = Query(None),
    vault: Any = Depends(get_vault),  # noqa: ARG001 - 503 if missing
) -> AuditList:
    """Return recent vault accesses (in-memory single-process log)."""
    state = get_state(request)
    entries: list[AuditEntry] = []
    for raw in state.vault_audit:
        if not isinstance(raw, dict):
            continue
        ts_raw = raw.get("timestamp")
        ts = (
            ts_raw
            if isinstance(ts_raw, datetime)
            else (datetime.fromisoformat(str(ts_raw)) if ts_raw else None)
        )
        if ts is None:
            continue
        if since is not None and ts < since:
            continue
        if provider is not None and raw.get("provider") != provider:
            continue
        if host is not None and raw.get("host") != host:
            continue
        if decision is not None and raw.get("decision") != decision:
            continue
        entries.append(
            AuditEntry(
                timestamp=ts,
                session_id=raw.get("session_id"),  # type: ignore[arg-type]
                provider=raw.get("provider"),  # type: ignore[arg-type]
                host=raw.get("host"),  # type: ignore[arg-type]
                decision=str(raw.get("decision", "unknown")),
                vault_id=raw.get("vault_id"),  # type: ignore[arg-type]
                detail=raw.get("detail"),  # type: ignore[arg-type]
            )
        )

    # Newest first.
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return AuditList(data=entries[:limit])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _audit(
    state: AppState,
    *,
    decision: str,
    provider: str | None = None,
    host: str | None = None,
    session_id: str | None = None,
    vault_id: str | None = None,
    detail: str | None = None,
) -> None:
    state.vault_audit.append(
        {
            "timestamp": datetime.now(timezone.utc),
            "decision": decision,
            "provider": provider,
            "host": host,
            "session_id": session_id,
            "vault_id": vault_id,
            "detail": detail,
        }
    )
    # Cap to 5k entries to keep memory bounded.
    if len(state.vault_audit) > 5000:
        del state.vault_audit[0 : len(state.vault_audit) - 5000]


__all__ = ["router"]
