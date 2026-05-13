"""End-to-end hello-world flow.

Exercises:
1. Server boots and answers basic listing endpoints.
2. Agent creation via the CLI client.
3. Session creation + send + event listing.

The harness loop itself only fires when ``ANTHROPIC_API_KEY`` is
present — we still validate the catalog API and event log without it.
"""

from __future__ import annotations

import time

import pytest

from wake.cli.client import WakeAPIError, WakeClient

pytestmark = pytest.mark.integration


def test_server_responds_to_list_agents(wake_client: WakeClient) -> None:
    """The simplest possible smoke test — server is up, list endpoint works."""
    agents = wake_client.list_agents()
    assert isinstance(agents, list)


def test_create_and_get_agent(wake_client: WakeClient) -> None:
    agent = wake_client.create_agent(
        name="hello-test",
        model="claude-opus-4-7",
        system="Reply briefly.",
        tools=None,
    )
    assert "id" in agent, "server must return an agent id"
    agent_id = agent["id"]
    fetched = wake_client.get_agent(agent_id)
    assert fetched.get("id") == agent_id
    assert fetched.get("name") == "hello-test"


def test_create_session_and_send_message(wake_client: WakeClient) -> None:
    agent = wake_client.create_agent(name="hello-session", model="claude-opus-4-7")
    session = wake_client.create_session(agent_id=agent["id"])
    assert "id" in session

    sent = wake_client.send_message(session["id"], "ping")
    # Server may return the event or just an ack — either is fine.
    assert isinstance(sent, dict)

    # The user.message we just sent should show up in the event log
    # almost immediately. Give it a short polling window.
    events: list[dict[str, object]] = []
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        events = wake_client.list_events(session["id"])
        if any(e.get("type") == "user.message" for e in events):
            break
        time.sleep(0.1)
    assert any(e.get("type") == "user.message" for e in events), (
        f"user.message not found in events: {events!r}"
    )


def test_404_surfaces_as_api_error(wake_client: WakeClient) -> None:
    with pytest.raises(WakeAPIError) as info:
        wake_client.get_agent("nonexistent-id-asdf")
    assert info.value.status_code in {404, 400}


@pytest.mark.usefixtures("require_anthropic_key")
def test_full_hello_world_completes(wake_client: WakeClient) -> None:
    """End-to-end: a real Claude reply lands in the log.

    Skips automatically without ``ANTHROPIC_API_KEY``.
    """
    agent = wake_client.create_agent(
        name="hello-e2e",
        model="claude-opus-4-7",
        system="Reply with exactly one sentence.",
    )
    session = wake_client.create_session(agent_id=agent["id"])
    wake_client.send_message(session["id"], "Say hello in 3 languages.")

    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        events = wake_client.list_events(session["id"])
        if any(e.get("type") == "assistant.message" for e in events):
            return
        time.sleep(0.5)
    pytest.fail("assistant.message never emitted within 60s")
