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


@router.post("/oauth/start", response_model=OAuthStartResponse)
async def oauth_start(
    body: OAuthStartRequest,
    request: Request,
    vault: Any = Depends(get_vault),  # noqa: ARG001 - 503 if vault missing
) -> OAuthStartResponse:
    """Start an OAuth Authorization Code flow for ``body.provider``."""
    if body.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown provider {body.provider!r}; expected one of {SUPPORTED_PROVIDERS}",
        )

    try:
        from wake_vault_infisical.oauth import OAuthFlow  # noqa: PLC0415
    except ImportError as exc:
        raise HTTPException(
            status_code=501, detail="OAuth helper not available"
        ) from exc

    state = get_state(request)
    cfg = _oauth_config(state, body.provider)
    if body.redirect_uri:
        cfg["redirect_uri"] = body.redirect_uri
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise HTTPException(
            status_code=500,
            detail=(
                f"OAuth client not configured for {body.provider!r} — set "
                f"WAKE_OAUTH_{body.provider.upper()}_CLIENT_ID and "
                f"WAKE_OAUTH_{body.provider.upper()}_CLIENT_SECRET."
            ),
        )

    flow = OAuthFlow.for_provider(
        body.provider,
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        redirect_uri=cfg["redirect_uri"],
    )
    url, csrf_state = flow.build_authorize_url(scopes=body.scopes)

    state.oauth_flows[csrf_state] = {
        "flow": flow,
        "provider": body.provider,
        "scopes": body.scopes or [],
        "created_at": datetime.now(timezone.utc),
    }

    _audit(state, decision="oauth_start", provider=body.provider)

    return OAuthStartResponse(provider=body.provider, auth_url=url, state=csrf_state)


# ---------------------------------------------------------------------------
# OAuth callback
# ---------------------------------------------------------------------------


@router.get("/oauth/callback", response_model=CredentialMetadataDTO)
async def oauth_callback(
    request: Request,
    code: str = Query(..., description="Authorization code from the provider"),
    state: str = Query(..., description="CSRF state echoed by the provider"),
    vault: Any = Depends(get_vault),
) -> CredentialMetadataDTO:
    """Exchange an OAuth ``code`` for an access token, then store it."""
    app_state = get_state(request)
    entry = app_state.oauth_flows.pop(state, None)
    if entry is None:
        raise HTTPException(status_code=400, detail="unknown or expired state")

    flow = entry.get("flow") if isinstance(entry, dict) else None
    provider = entry.get("provider", "custom") if isinstance(entry, dict) else "custom"
    scopes = list(entry.get("scopes", [])) if isinstance(entry, dict) else []

    if flow is None:
        raise HTTPException(status_code=400, detail="malformed oauth state entry")

    try:
        data = await flow.exchange_code(code, state=state)
    except Exception as exc:
        logger.exception("oauth_callback_failed", provider=provider)
        _audit(app_state, decision="oauth_failed", provider=str(provider), detail=str(exc))
        raise HTTPException(status_code=400, detail=f"OAuth exchange failed: {exc}") from exc

    token: str = str(data.get("access_token", ""))
    if not token:
        raise HTTPException(status_code=502, detail="provider returned empty token")

    name = f"{provider}_token_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    try:
        meta = await vault.add(
            name=name,
            provider=str(provider),
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
        provider=str(provider),
        vault_id=getattr(meta, "vault_id", None),
    )

    return CredentialMetadataDTO(
        vault_id=getattr(meta, "vault_id", ""),
        name=getattr(meta, "name", name),
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
    """Start a new OAuth flow for the same provider; callback will replace.

    Rotation is two-step: this endpoint returns a fresh auth URL; the
    UI sends the user through it, and the callback path stores the new
    token. The old credential is **not** revoked here so an in-flight
    session can finish using it; ``DELETE`` is the explicit revoke.
    """
    try:
        meta = await vault.get_metadata(vault_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"credential not found: {exc}") from exc

    provider = str(getattr(meta, "provider", "custom"))
    scopes = list(getattr(meta, "scopes", []) or [])

    start_resp = await oauth_start(
        OAuthStartRequest(provider=provider, scopes=scopes, redirect_uri=body.redirect_uri),
        request=request,
        vault=vault,
    )

    _audit(
        get_state(request),
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
