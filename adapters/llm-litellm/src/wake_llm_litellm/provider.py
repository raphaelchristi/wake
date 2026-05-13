"""LiteLLMProvider — concrete ``LLMProvider`` backed by ``litellm.acompletion``."""

from __future__ import annotations

from typing import Any

import structlog

from wake_llm_litellm.base import (
    LLMProvider,
    LLMProviderError,
    NormalizedMessage,
)
from wake_llm_litellm.cost_tracking import install_litellm_callback
from wake_llm_litellm.normalize import normalize_response

logger = structlog.get_logger(__name__)


class LiteLLMProvider(LLMProvider):
    """``LLMProvider`` that delegates to ``litellm.acompletion``.

    LiteLLM dispatches to ~100 model providers using one API. We pass
    requests through unchanged (other than injecting ``metadata`` for
    cost tracking) and normalise the response into a Wake-canonical
    ``NormalizedMessage``.

    Parameters
    ----------
    completion_fn
        Optional injection point for tests / custom routing. Defaults
        to ``litellm.acompletion``.
    install_cost_tracking
        Whether to register the LiteLLM ``success_callback`` for cost
        accounting on initialisation. Defaults to ``True``.
    default_kwargs
        kwargs forwarded to every ``acompletion`` call (e.g.
        ``{"api_base": "http://localhost:11434"}`` for Ollama).
    """

    def __init__(
        self,
        completion_fn: Any | None = None,
        *,
        install_cost_tracking: bool = True,
        default_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self._completion_fn = completion_fn
        self._default_kwargs = dict(default_kwargs or {})
        if install_cost_tracking and completion_fn is None:
            # Only register the global callback when we are actually
            # going to use real litellm; injected fakes don't need it.
            install_litellm_callback()

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
        fn = self._completion_fn
        if fn is None:
            try:
                import litellm
            except ImportError as exc:  # pragma: no cover — hard dep
                raise LLMProviderError(
                    "litellm is not installed; install wake-llm-litellm or pass a custom completion_fn"
                ) from exc
            fn = litellm.acompletion

        # ----- assemble payload -----
        call_kwargs: dict[str, Any] = dict(self._default_kwargs)
        call_kwargs["model"] = model
        # Anthropic-style system → litellm: pass as separate kwarg; for
        # OpenAI providers litellm folds it into a system message itself.
        call_messages = list(messages)
        # If the caller already provided a system message at index 0 we leave their
        # version; otherwise prepend the fallback. (Combined into one condition for
        # ruff SIM102.)
        if system and (not call_messages or call_messages[0].get("role") != "system"):
            call_messages = [{"role": "system", "content": system}, *call_messages]
        call_kwargs["messages"] = call_messages
        call_kwargs["max_tokens"] = max_tokens
        if tools:
            call_kwargs["tools"] = self._render_tools(tools, model)
        # Caller overrides everything else.
        call_kwargs.update(kwargs)

        logger.info(
            "litellm_acompletion",
            model=model,
            n_messages=len(call_messages),
            n_tools=len(tools or []),
        )

        try:
            response = await fn(**call_kwargs)
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"litellm completion failed: {exc}") from exc

        return normalize_response(response, model=model)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _render_tools(
        tools: list[dict[str, Any]], model: str
    ) -> list[dict[str, Any]]:
        """Convert Anthropic-shaped tools → OpenAI-shaped if needed.

        LiteLLM accepts both shapes, but to avoid ambiguity for non-
        Anthropic providers we explicitly translate. For Anthropic
        models we pass through verbatim (LiteLLM unwraps appropriately).
        """
        if model.lower().startswith(("anthropic/", "claude-")):
            return tools

        out: list[dict[str, Any]] = []
        for t in tools:
            if "function" in t:  # already OpenAI-shaped
                out.append(t)
                continue
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema") or t.get("parameters") or {},
                    },
                }
            )
        return out


def create() -> LiteLLMProvider:
    """Entry-point factory used by the ``wake.llm_providers`` loader."""
    return LiteLLMProvider()


__all__ = ["LiteLLMProvider", "create"]
