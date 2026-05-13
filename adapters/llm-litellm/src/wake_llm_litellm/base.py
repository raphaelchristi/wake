"""LLMProvider ABC + normalized intermediate types.

The Phase 4 Wake substrate plugs in arbitrary model providers via this
interface. The HarnessAdapter (Claude SDK, LangGraph, …) constructs its
LLM request, calls ``create_message``, and converts the **normalized**
response into Wake events.

Intermediate types
------------------

* ``NormalizedToolCall`` — one tool invocation the model wants.
* ``NormalizedMessage`` — text + zero or more tool calls + usage + stop.

All providers funnel through these so the adapter never has to know
"is this Anthropic format or OpenAI format".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

StopReason = Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "error"]


class LLMProviderError(Exception):
    """Raised on transport / parsing failures."""


class NormalizedToolCall(BaseModel):
    """Wake-canonical view of a single tool the model wants to run."""

    model_config = ConfigDict(frozen=True)

    id: str  # provider-supplied id (e.g. ``toolu_01XYZ``); ``"" `` if absent
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class NormalizedMessage(BaseModel):
    """Wake-canonical assistant message after provider normalization.

    Maps cleanly to the Wake ``assistant.message`` event payload plus
    follow-on ``tool_use`` events.
    """

    model_config = ConfigDict(frozen=True)

    text: str = ""
    tool_calls: list[NormalizedToolCall] = Field(default_factory=list)
    stop_reason: StopReason = "end_turn"
    # Token usage in the Anthropic-shaped form ({input_tokens, output_tokens, …}).
    usage: dict[str, Any] = Field(default_factory=dict)
    # Per-provider raw response for adapters that need to dig deeper.
    raw: dict[str, Any] = Field(default_factory=dict)
    # Cost (USD) if the provider reports it (LiteLLM ``response_cost``).
    cost_usd: float | None = None


class LLMProvider(ABC):
    """Common interface every LLM provider implements.

    Concrete providers wrap their SDK (Anthropic, OpenAI, Ollama, …) or
    a meta-router like LiteLLM. The contract is intentionally tiny:
    one async method that takes a request and returns a normalized
    response.

    Providers are expected to be **stateless across calls** — concurrent
    sessions may invoke the same instance simultaneously.
    """

    @abstractmethod
    async def create_message(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> NormalizedMessage:
        """Send one completion request and return the normalized result.

        ``messages`` follows the Anthropic Messages API shape ({role,
        content}); LiteLLM internally rewrites them per-provider.

        ``tools`` follows the Anthropic ``tools`` array shape (i.e. each
        entry has ``name``, ``description``, ``input_schema``). LiteLLM
        converts to OpenAI/Ollama shapes downstream.
        """


__all__ = [
    "LLMProvider",
    "LLMProviderError",
    "NormalizedToolCall",
    "NormalizedMessage",
    "StopReason",
]
