"""Tests for the OAuth helper.

Uses ``httpx.MockTransport`` to mock token endpoints — no network.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from wake_vault_infisical.oauth import (
    OAuthError,
    OAuthFlow,
    OAuthProvider,
    get_provider,
    register_provider,
)


def _flow_for(provider_name: str, transport: httpx.MockTransport) -> OAuthFlow:
    return OAuthFlow.for_provider(
        provider_name,
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://localhost:8765/callback",
        http_client=httpx.AsyncClient(transport=transport),
    )


def test_get_provider_known() -> None:
    p = get_provider("github")
    assert p.name == "github"
    assert "repo" in p.default_scopes


def test_get_provider_unknown_raises() -> None:
    with pytest.raises(KeyError):
        get_provider("does-not-exist")


def test_build_authorize_url_github() -> None:
    flow = OAuthFlow.for_provider(
        "github",
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://localhost:8765/cb",
    )
    url, state = flow.build_authorize_url(scopes=["repo", "read:user"])
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=cid" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8765%2Fcb" in url
    # GitHub uses space-separated scopes (URL-encoded as +).
    assert "scope=repo+read%3Auser" in url
    assert f"state={state}" in url
    assert "response_type=code" in url


def test_build_authorize_url_slack_uses_comma_separator() -> None:
    flow = OAuthFlow.for_provider(
        "slack",
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://localhost/cb",
    )
    url, _ = flow.build_authorize_url(scopes=["chat:write", "channels:read"])
    assert "scope=chat%3Awrite%2Cchannels%3Aread" in url


def test_build_authorize_url_notion_omits_scope_param() -> None:
    flow = OAuthFlow.for_provider(
        "notion",
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://localhost/cb",
    )
    url, _ = flow.build_authorize_url()
    assert "scope=" not in url
    # Provider declares extra params.
    assert "owner=user" in url


def test_state_is_csrf_token_and_remembered() -> None:
    flow = OAuthFlow.for_provider(
        "github", client_id="x", client_secret="y", redirect_uri="http://l/cb"
    )
    _, state = flow.build_authorize_url()
    assert len(state) > 16
    assert flow.state == state


async def test_exchange_code_happy_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/login/oauth/access_token"
        # Provider received the right body.
        body = dict(p.split("=", 1) for p in request.content.decode().split("&"))
        assert body["client_id"] == "cid"
        assert body["code"] == "auth_code_42"
        return httpx.Response(
            200,
            json={"access_token": "ghp_real_token", "token_type": "bearer", "scope": "repo"},
        )

    flow = _flow_for("github", httpx.MockTransport(handler))
    flow.build_authorize_url()  # set state

    data = await flow.exchange_code("auth_code_42", state=flow.state)
    assert data["access_token"] == "ghp_real_token"


async def test_exchange_code_state_mismatch_raises() -> None:
    flow = OAuthFlow.for_provider(
        "github", client_id="x", client_secret="y", redirect_uri="http://l/cb"
    )
    flow.build_authorize_url()
    with pytest.raises(OAuthError, match="state mismatch"):
        await flow.exchange_code("c", state="wrong-state")


async def test_exchange_code_empty_code_raises() -> None:
    flow = OAuthFlow.for_provider(
        "github", client_id="x", client_secret="y", redirect_uri="http://l/cb"
    )
    with pytest.raises(OAuthError, match="empty authorization code"):
        await flow.exchange_code("")


async def test_exchange_code_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    flow = _flow_for("github", httpx.MockTransport(handler))
    with pytest.raises(OAuthError, match="HTTP 500"):
        await flow.exchange_code("c")


async def test_exchange_code_provider_explicit_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"error": "access_denied", "error_description": "user said no"}
        )

    flow = _flow_for("github", httpx.MockTransport(handler))
    with pytest.raises(OAuthError, match="access_denied"):
        await flow.exchange_code("c")


async def test_exchange_code_non_json_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", headers={"content-type": "text/plain"})

    flow = _flow_for("github", httpx.MockTransport(handler))
    with pytest.raises(OAuthError, match="non-JSON"):
        await flow.exchange_code("c")


def test_register_custom_provider() -> None:
    custom = OAuthProvider(
        name="acme",
        authorize_url="https://acme.example/auth",
        token_url="https://acme.example/token",
        default_scopes=["read"],
    )
    register_provider(custom)
    assert get_provider("acme").name == "acme"


async def test_token_value_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Smoke-test: after a successful exchange, the actual token value
    must not appear in any captured log record."""

    secret_token = "ghp_THIS_MUST_NEVER_LEAK"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": secret_token})

    flow = _flow_for("github", httpx.MockTransport(handler))
    flow.build_authorize_url()
    with caplog.at_level("INFO"):
        data: dict[str, Any] = await flow.exchange_code("c", state=flow.state)
    assert data["access_token"] == secret_token
    for record in caplog.records:
        assert secret_token not in record.getMessage()
        assert secret_token not in str(record.args or "")
