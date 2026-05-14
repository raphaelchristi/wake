"""Convenience helpers for working with event payloads.

The Wake server emits events with arbitrary ``payload`` dicts; these helpers
extract the most common bits (text deltas, tool calls, errors) so consumers
don't have to reach into payload keys directly.
"""

from __future__ import annotations

from wake_ai_client.types import Event


def extract_text(event: Event) -> str | None:
    """Return the assistant text on ``assistant.message`` / ``assistant.delta``.

    Handles both the legacy ``text`` string payload and the canonical
    ``content`` block list.
    """
    if event.type not in ("assistant.message", "assistant.delta"):
        return None
    payload = event.payload or {}
    if isinstance(payload.get("text"), str):
        return payload["text"]
    content = payload.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts)
    return None


def is_terminal(event: Event) -> bool:
    """True if an event marks the end of a session loop."""
    if event.type == "error":
        return True
    if event.type == "status":
        return (event.payload or {}).get("status") == "terminated"
    return False


__all__ = ["extract_text", "is_terminal"]
