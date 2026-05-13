"""Unit tests for the CLI HTTP client.

These don't talk to a real server — we either inspect pure helpers
(``resolve_server``, ``_coerce_list``, ``_summarise_error``) or mock
``httpx`` via ``MockTransport``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from wake.cli import client as client_mod
from wake.cli.client import (
    DEFAULT_SERVER,
    WakeAPIError,
    WakeClient,
    _coerce_list,
    _summarise_error,
    resolve_server,
)


def test_resolve_server_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WAKE_SERVER", raising=False)
    assert resolve_server() == DEFAULT_SERVER

    monkeypatch.setenv("WAKE_SERVER", "http://from-env:9000/")
    assert resolve_server() == "http://from-env:9000"

    # Explicit override wins.
    assert resolve_server("http://explicit:1234/") == "http://explicit:1234"


def test_summarise_error_with_detail() -> None:
    body = json.dumps({"detail": "agent not found"})
    msg = _summarise_error(404, body)
    assert "404" in msg
    assert "agent not found" in msg


def test_summarise_error_plain_text() -> None:
    msg = _summarise_error(500, "internal explosion")
    assert "500" in msg
    assert "internal explosion" in msg


def test_summarise_error_empty_body() -> None:
    assert _summarise_error(503, "") == "HTTP 503"


def test_coerce_list_variants() -> None:
    assert _coerce_list(None) == []
    assert _coerce_list([{"id": "a"}, "drop-this", {"id": "b"}]) == [
        {"id": "a"},
        {"id": "b"},
    ]
    assert _coerce_list({"data": [{"id": "a"}]}) == [{"id": "a"}]
    assert _coerce_list({"items": [{"id": "a"}]}) == [{"id": "a"}]
    assert _coerce_list("nonsense") == []


def _make_client(handler: httpx.MockTransport) -> WakeClient:
    """Build a WakeClient whose underlying httpx.Client uses a mock transport."""
    client = WakeClient("http://test.local")
    client._client.close()
    client._client = httpx.Client(  # type: ignore[assignment]
        base_url="http://test.local",
        transport=handler,
    )
    return client


def test_create_agent_sends_expected_body() -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["url"] = str(request.url)
        received["method"] = request.method
        received["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "agt_1", "name": "hi"})

    client = _make_client(httpx.MockTransport(handler))
    agent = client.create_agent(
        name="hi",
        model="claude-opus-4-7",
        system="be brief",
        tools=["bash", "file_read"],
        metadata={"team": "platform"},
    )
    client.close()

    assert agent == {"id": "agt_1", "name": "hi"}
    assert received["method"] == "POST"
    body = received["body"]
    assert isinstance(body, dict)
    assert body["name"] == "hi"
    assert body["model"] == {"id": "claude-opus-4-7"}
    assert body["system"] == "be brief"
    assert body["tools"] == [{"type": "bash"}, {"type": "file_read"}]
    assert body["metadata"] == {"team": "platform"}


def test_send_message_wraps_text_block() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"seq": 0, "type": "user.message"})

    client = _make_client(httpx.MockTransport(handler))
    result = client.send_message("sess_1", "hello")
    client.close()

    assert result["seq"] == 0
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["type"] == "user.message"
    assert body["payload"] == {"content": [{"type": "text", "text": "hello"}]}


def test_http_error_raises_wake_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "missing"})

    client = _make_client(httpx.MockTransport(handler))
    with pytest.raises(WakeAPIError) as info:
        client.get_agent("nope")
    client.close()
    assert info.value.status_code == 404
    assert "missing" in str(info.value)


def test_list_endpoints_coerce_data_wrapper() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}]})

    client = _make_client(httpx.MockTransport(handler))
    agents = client.list_agents()
    client.close()
    assert agents == [{"id": "a"}, {"id": "b"}]


def test_stream_url_builds_correctly() -> None:
    c = WakeClient("http://example.test:1234/")
    assert c.stream_url("sess_x") == "http://example.test:1234/v1/sessions/sess_x/stream"
    c.close()


def test_module_exports() -> None:
    # Catches accidental removals of public surface.
    assert "WakeClient" in client_mod.__all__
    assert "stream_events" in client_mod.__all__
