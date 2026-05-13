"""Legacy harness namespace.

Phase 1 hardcoded the Anthropic SDK loop here. Phase 2 lifted it onto the
``HarnessAdapter`` ABI in ``wake.adapters`` + ``wake.runtime``; the
canonical implementation now lives in ``wake_adapter_claude_sdk``.

This module re-exports the Phase 1 symbols (``AnthropicHarness``,
``events_to_messages``) as a thin compat shim. New code should import
``ClaudeSDKAdapter`` from ``wake_adapter_claude_sdk`` and drive it via
``wake.runtime.SessionDispatcher``.
"""

from wake.harness.anthropic import MAX_RECURSION, AnthropicHarness, events_to_messages

__all__ = ["AnthropicHarness", "events_to_messages", "MAX_RECURSION"]
