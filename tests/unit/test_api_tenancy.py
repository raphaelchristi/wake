"""API tenancy isolation tests.

The public API should treat workspace as the data isolation boundary. The
headers used here intentionally stay generic: any AI product can map its
customer/project/account model to these Wake primitives at the gateway layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient


def _tenant(workspace_id: str, organization_id: str = "org_test") -> dict[str, str]:
    return {
        "X-Wake-Organization-Id": organization_id,
        "X-Wake-Workspace-Id": workspace_id,
    }


@pytest.mark.asyncio
async def test_agents_are_scoped_to_request_workspace(client: AsyncClient) -> None:
    a = (
        await client.post(
            "/v1/agents",
            headers=_tenant("workspace_a"),
            json={"name": "a", "model": {"id": "claude-opus-4-7"}},
        )
    ).json()
    await client.post(
        "/v1/agents",
        headers=_tenant("workspace_b"),
        json={"name": "b", "model": {"id": "claude-opus-4-7"}},
    )

    assert a["organization_id"] == "org_test"
    assert a["workspace_id"] == "workspace_a"

    visible = await client.get("/v1/agents", headers=_tenant("workspace_a"))
    assert visible.status_code == 200
    assert [agent["name"] for agent in visible.json()["data"]] == ["a"]

    hidden = await client.get(f"/v1/agents/{a['id']}", headers=_tenant("workspace_b"))
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_sessions_cannot_use_agents_from_another_workspace(
    client: AsyncClient,
) -> None:
    agent = (
        await client.post(
            "/v1/agents",
            headers=_tenant("workspace_a"),
            json={"name": "a", "model": {"id": "claude-opus-4-7"}},
        )
    ).json()

    res = await client.post(
        "/v1/sessions",
        headers=_tenant("workspace_b"),
        json={"agent_id": agent["id"]},
    )

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_sessions_and_events_are_scoped_to_request_workspace(
    client: AsyncClient,
) -> None:
    agent = (
        await client.post(
            "/v1/agents",
            headers=_tenant("workspace_a"),
            json={"name": "a", "model": {"id": "claude-opus-4-7"}},
        )
    ).json()
    session = (
        await client.post(
            "/v1/sessions",
            headers=_tenant("workspace_a"),
            json={"agent_id": agent["id"]},
        )
    ).json()
    await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=_tenant("workspace_a"),
        json={"type": "status", "payload": {"from": "idle", "to": "idle"}},
    )

    assert session["workspace_id"] == "workspace_a"

    visible = await client.get("/v1/sessions", headers=_tenant("workspace_a"))
    assert [s["id"] for s in visible.json()["data"]] == [session["id"]]

    hidden_session = await client.get(
        f"/v1/sessions/{session['id']}",
        headers=_tenant("workspace_b"),
    )
    assert hidden_session.status_code == 404

    hidden_events = await client.get(
        f"/v1/sessions/{session['id']}/events",
        headers=_tenant("workspace_b"),
    )
    assert hidden_events.status_code == 404
