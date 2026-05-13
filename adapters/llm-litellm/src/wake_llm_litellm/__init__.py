"""Wake LLMProvider backed by LiteLLM.

LiteLLM gives us one API surface against 100+ model providers. This
adapter normalises provider-specific responses (Anthropic ``tool_use``
blocks, OpenAI ``tool_calls`` array, Ollama ``function`` calls) into
the canonical Wake ``tool_use`` / ``tool_result`` event shape so the
runtime is provider-agnostic.

Cost tracking is wired through LiteLLM's ``success_callback`` hook —
each completion's ``response_cost`` and token usage land in event
``metadata`` so SaaS-style billing or per-session budgeting is a
straightforward downstream concern.
"""

from wake_llm_litellm.base import (
    LLMProvider,
    LLMProviderError,
    NormalizedMessage,
    NormalizedToolCall,
)
from wake_llm_litellm.cost_tracking import (
    CostMetadata,
    CostTracker,
    install_litellm_callback,
)
from wake_llm_litellm.normalize import (
    normalize_completion,
    normalize_response,
    to_wake_events,
)
from wake_llm_litellm.provider import LiteLLMProvider, create

__all__ = [
    "LLMProvider",
    "LLMProviderError",
    "LiteLLMProvider",
    "NormalizedMessage",
    "NormalizedToolCall",
    "normalize_response",
    "normalize_completion",
    "to_wake_events",
    "CostMetadata",
    "CostTracker",
    "install_litellm_callback",
    "create",
]

__version__ = "0.1.0"
