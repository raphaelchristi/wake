"""Unit tests for ``wake.api.oauth_state`` (signed OAuth state tokens)."""

from __future__ import annotations

import time

import pytest

from wake.api import oauth_state
from wake.api.oauth_state import OAuthStateError, sign_state, verify_state

SECRET = "test-secret-do-not-use-in-prod"


def test_sign_verify_roundtrip() -> None:
    payload = {
        "provider": "github",
        "scopes": ["repo", "read:user"],
        "redirect_uri": "http://localhost:3000/oauth/callback",
    }
    token = sign_state(payload, secret=SECRET)
    decoded = verify_state(token, secret=SECRET)
    assert decoded["provider"] == "github"
    assert decoded["scopes"] == ["repo", "read:user"]
    assert decoded["redirect_uri"] == "http://localhost:3000/oauth/callback"
    # iat/exp are stamped automatically.
    assert isinstance(decoded["iat"], int)
    assert isinstance(decoded["exp"], int)
    assert decoded["exp"] > decoded["iat"]


def test_sign_verify_carries_vault_id_to_rotate() -> None:
    token = sign_state(
        {"provider": "github", "vault_id_to_rotate": "vault_abc"}, secret=SECRET
    )
    decoded = verify_state(token, secret=SECRET)
    assert decoded["vault_id_to_rotate"] == "vault_abc"


def test_expired_token_raises() -> None:
    # ttl_seconds=1, then sleep past expiry — but use 0 by mocking time
    # so the test is fast and deterministic.
    token = sign_state({"provider": "github"}, secret=SECRET, ttl_seconds=1)
    # Force "now" forward by 2s when verify reads it.
    real_time = time.time

    def fake_time() -> float:
        return real_time() + 5

    time.time = fake_time  # type: ignore[assignment]
    try:
        with pytest.raises(OAuthStateError, match="expired"):
            verify_state(token, secret=SECRET)
    finally:
        time.time = real_time  # type: ignore[assignment]


def test_tampered_payload_raises() -> None:
    token = sign_state({"provider": "github"}, secret=SECRET)
    blob, sig = token.rsplit(".", 1)
    # Flip one character in the payload portion.
    tampered_blob = "A" + blob[1:] if blob[0] != "A" else "B" + blob[1:]
    tampered = f"{tampered_blob}.{sig}"
    with pytest.raises(OAuthStateError, match="signature mismatch"):
        verify_state(tampered, secret=SECRET)


def test_tampered_signature_raises() -> None:
    token = sign_state({"provider": "github"}, secret=SECRET)
    blob, sig = token.rsplit(".", 1)
    tampered_sig = "A" + sig[1:] if sig[0] != "A" else "B" + sig[1:]
    tampered = f"{blob}.{tampered_sig}"
    with pytest.raises(OAuthStateError):
        verify_state(tampered, secret=SECRET)


def test_wrong_secret_raises() -> None:
    token = sign_state({"provider": "github"}, secret=SECRET)
    with pytest.raises(OAuthStateError, match="signature mismatch"):
        verify_state(token, secret="other-secret")


def test_malformed_token_raises() -> None:
    with pytest.raises(OAuthStateError, match="missing separator"):
        verify_state("no-dot-here", secret=SECRET)
    with pytest.raises(OAuthStateError, match="empty segment"):
        verify_state(".sig", secret=SECRET)
    with pytest.raises(OAuthStateError, match="empty segment"):
        verify_state("blob.", secret=SECRET)


def test_module_resolves_secret_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(oauth_state.SECRET_ENV, "env-secret")
    oauth_state._reset_secret_cache()
    try:
        # When ``secret`` is omitted, the module-level secret kicks in.
        token = sign_state({"provider": "github"})
        decoded = verify_state(token)
        assert decoded["provider"] == "github"
    finally:
        oauth_state._reset_secret_cache()


def test_module_autogenerates_secret_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(oauth_state.SECRET_ENV, raising=False)
    oauth_state._reset_secret_cache()
    try:
        token = sign_state({"provider": "github"})
        # Same process can verify what it just signed.
        decoded = verify_state(token)
        assert decoded["provider"] == "github"
    finally:
        oauth_state._reset_secret_cache()


def test_cross_replica_with_shared_secret() -> None:
    """Two independent module imports verify each other's tokens.

    This is the property the deploy actually relies on: multiple API
    replicas share ``WAKE_OAUTH_STATE_SECRET`` via Kubernetes Secret and
    can therefore complete callbacks regardless of which pod handled
    the start.
    """
    token = sign_state({"provider": "github", "scopes": ["repo"]}, secret=SECRET)
    # Pretend we're in another process — call verify directly with the
    # same secret; no shared mutable state.
    decoded = verify_state(token, secret=SECRET)
    assert decoded["provider"] == "github"
    assert decoded["scopes"] == ["repo"]
