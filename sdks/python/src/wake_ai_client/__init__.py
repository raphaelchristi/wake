"""Wake AI Python client — async-first SDK.

Quickstart
----------

::

    import asyncio
    from wake_ai_client import WakeClient

    async def main():
        async with WakeClient(
            base_url="https://wake.example.com",
            api_key="sk-wake-...",
            organization_id="org-acme",
            workspace_id="ws-default",
        ) as client:
            agents = await client.agents.list()
            print(agents)

            session = await client.sessions.create(agent_id=agents[0].id)
            async for event in client.sessions.stream(session.id):
                print(event.type, event.payload)

    asyncio.run(main())

The factory also reads ``WAKE_API_KEY`` from the environment as a fallback when
``api_key`` is not provided explicitly.
"""

from __future__ import annotations

from wake_ai_client.client import WakeClient
from wake_ai_client.exceptions import (
    WakeAPIError,
    WakeAuthError,
    WakeClientError,
    WakeNotFoundError,
    WakeRateLimitError,
    WakeServerError,
    WakeTransportError,
)
from wake_ai_client.types import (
    AgentConfig,
    AgentList,
    ContentBlock,
    Event,
    EventList,
    EventType,
    ImageBlock,
    McpServerConfig,
    ModelConfig,
    Session,
    SessionList,
    SessionStatus,
    TextBlock,
    ToolConfig,
    ToolResultBlock,
    ToolUseBlock,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "WakeClient",
    # exceptions
    "WakeClientError",
    "WakeAPIError",
    "WakeAuthError",
    "WakeNotFoundError",
    "WakeRateLimitError",
    "WakeServerError",
    "WakeTransportError",
    # types
    "AgentConfig",
    "AgentList",
    "ContentBlock",
    "Event",
    "EventList",
    "EventType",
    "ImageBlock",
    "McpServerConfig",
    "ModelConfig",
    "Session",
    "SessionList",
    "SessionStatus",
    "TextBlock",
    "ToolConfig",
    "ToolResultBlock",
    "ToolUseBlock",
]
