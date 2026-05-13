"""Wake HarnessAdapter for the Anthropic Claude SDK.

Implements the ``HarnessAdapter`` Protocol declared in
``wake.adapters`` against the Anthropic Messages API (streaming).

The adapter is a thin generator: it reads events from the supplied
``EventStream``, builds a Messages API request, streams the response,
yields canonical Wake events back to the runtime, and recurses on
``tool_use`` until the model emits ``end_turn`` (or ``max_recursion`` is
reached).
"""

from wake_adapter_claude_sdk.adapter import (
    MAX_RECURSION,
    ClaudeSDKAdapter,
    events_to_messages,
)

__all__ = [
    "ClaudeSDKAdapter",
    "events_to_messages",
    "MAX_RECURSION",
]

__version__ = "0.1.0"
