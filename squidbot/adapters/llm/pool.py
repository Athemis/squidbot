"""
Pooled LLM adapter with sequential fallback.

Wraps an ordered list of LLMPort instances. On any exception from the active
adapter the next one is tried. AuthenticationError is additionally logged at
WARNING level so the user sees credential failures even when a fallback succeeds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from squidbot.core.models import Message, ToolDefinition


def _is_auth_error(exc: Exception) -> bool:
    """Return True if the exception looks like an authentication failure."""
    return "AuthenticationError" in type(exc).__name__


async def _pool_gen(
    adapters: list[Any],
    messages: list[Message],
    tools: list[ToolDefinition],
    stream: bool,
) -> AsyncIterator[str | list[Any]]:
    """
    Async generator that tries each adapter in order, falling back on error.

    Args:
        adapters: Ordered list of LLMPort instances.
        messages: Full conversation history.
        tools: Available tool definitions.
        stream: Whether to stream the response.

    Raises:
        Exception: The last exception raised if all adapters fail.
    """
    last_exc: Exception | None = None
    for i, adapter in enumerate(adapters):
        try:
            async for chunk in await adapter.chat(messages, tools, stream=stream):
                yield chunk
            return
        except Exception as exc:
            if _is_auth_error(exc):
                logger.warning(
                    "llm pool: auth error on adapter {} ({}), trying next",
                    i,
                    type(exc).__name__,
                )
            else:
                logger.info(
                    "llm pool: error on adapter {} ({}), trying next",
                    i,
                    type(exc).__name__,
                )
            last_exc = exc
    raise last_exc  # type: ignore[misc]


class PooledLLMAdapter:
    """
    LLM adapter that tries a list of adapters in order, falling back on error.

    Implements LLMPort via structural subtyping (no explicit inheritance).
    All exceptions trigger fallback. AuthenticationError is additionally logged
    at WARNING so the user sees credential failures even when fallback succeeds.
    """

    def __init__(self, adapters: list[Any]) -> None:
        """
        Args:
            adapters: Ordered list of LLMPort instances. First is tried first.

        Raises:
            ValueError: If adapters list is empty.
        """
        if not adapters:
            raise ValueError("PooledLLMAdapter requires at least one adapter")
        self._adapters = adapters

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        """Return True if the exception looks like an authentication failure."""
        return _is_auth_error(exc)

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        stream: bool = True,
    ) -> AsyncIterator[str | list[Any]]:
        """
        Try each adapter in order, falling back to the next on any exception.

        Returns an AsyncIterator that yields chunks from the first adapter that
        succeeds. If all adapters fail, re-raises the last exception.

        Args:
            messages: Full conversation history.
            tools: Available tool definitions.
            stream: Whether to stream the response.

        Returns:
            AsyncIterator yielding str chunks or list[ToolCall] events.

        Raises:
            Exception: The last exception if all adapters fail.
        """
        return _pool_gen(self._adapters, messages, tools, stream)
