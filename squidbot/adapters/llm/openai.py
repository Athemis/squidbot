"""OpenAI-compatible LLM adapter.

Works with any provider that exposes an OpenAI-compatible API:
OpenAI, Anthropic (via OpenRouter), local vLLM, LM Studio, etc.

The adapter streams responses and surfaces tool calls as structured events.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from squidbot.core.models import Message, ToolCall, ToolDefinition


def _extract_reasoning_content(message_part: Any) -> str | None:
    direct = getattr(message_part, "reasoning_content", None)
    if isinstance(direct, str):
        return direct

    alt = getattr(message_part, "reasoning", None)
    if isinstance(alt, str):
        return alt

    model_extra = getattr(message_part, "model_extra", None)
    if isinstance(model_extra, dict):
        extra_reasoning = model_extra.get("reasoning_content")
        if isinstance(extra_reasoning, str):
            return extra_reasoning
        extra_alt = model_extra.get("reasoning")
        if isinstance(extra_alt, str):
            return extra_alt

    if isinstance(message_part, dict):
        dict_reasoning = message_part.get("reasoning_content")
        if isinstance(dict_reasoning, str):
            return dict_reasoning
        dict_alt = message_part.get("reasoning")
        if isinstance(dict_alt, str):
            return dict_alt

    return None


class OpenAIAdapter:
    """
    LLM adapter for OpenAI-compatible endpoints.

    Implements LLMPort via structural subtyping (no explicit inheritance).
    """

    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        supports_reasoning_content: bool = False,
    ) -> None:
        """
        Args:
            api_base: Base URL for the API (e.g., "https://openrouter.ai/api/v1").
            api_key: API key for authentication.
            model: Model identifier (e.g., "anthropic/claude-opus-4-5").
            supports_reasoning_content: Whether provider supports reasoning content fields.
        """
        self._client = AsyncOpenAI(base_url=api_base, api_key=api_key)
        self._model = model
        self._supports_reasoning_content = supports_reasoning_content

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        stream: bool = True,
    ) -> AsyncIterator[str | list[ToolCall] | tuple[list[ToolCall], str | None]]:
        """
        Send messages to the LLM and stream the response.

        Yields:
        - str chunks for text content (suitable for streaming to the user)
        - list[ToolCall] when the model requests tool execution (end of turn) without reasoning
        - tuple of (list[ToolCall], reasoning_content | None) when model provides reasoning
        """
        openai_messages = [
            m.to_openai_dict(include_reasoning_content=self._supports_reasoning_content)
            for m in messages
        ]
        openai_tools = [t.to_openai_dict() for t in tools] if tools else None

        if stream:
            return self._stream(openai_messages, openai_tools)
        else:
            return self._complete(openai_messages, openai_tools)

    async def _stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[str | list[ToolCall] | tuple[list[ToolCall], str | None]]:
        """Stream response chunks and accumulate tool calls."""
        accumulated_tool_calls: dict[int, dict[str, Any]] = {}
        accumulated_reasoning: list[str] = []

        kwargs: dict[str, Any] = {"model": self._model, "messages": messages, "stream": True}
        if tools:
            kwargs["tools"] = tools

        async with await self._client.chat.completions.create(**kwargs) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                # Accumulate text
                if delta.content:
                    yield delta.content

                # Accumulate reasoning content (for thinking models like Kimi K2.5)
                reasoning_chunk = _extract_reasoning_content(delta)
                if reasoning_chunk is not None:
                    accumulated_reasoning.append(reasoning_chunk)

                # Accumulate tool call fragments
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {
                                "id": tc_delta.id or "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc_delta.function:
                            if tc_delta.function.name:
                                accumulated_tool_calls[idx]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                accumulated_tool_calls[idx]["arguments"] += (
                                    tc_delta.function.arguments
                                )

        # Emit tool calls at the end of the stream
        if accumulated_tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    name=tc["name"],
                    arguments=json.loads(tc["arguments"]) if tc["arguments"] else {},
                )
                for tc in accumulated_tool_calls.values()
            ]
            reasoning = "".join(accumulated_reasoning) if accumulated_reasoning else None
            if reasoning is not None:
                yield (tool_calls, reasoning)
            else:
                yield tool_calls

    async def _complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[str | list[ToolCall] | tuple[list[ToolCall], str | None]]:
        """Non-streaming completion."""
        kwargs: dict[str, Any] = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        if choice.message.content:
            yield choice.message.content

        # Capture reasoning content for thinking models (e.g., Kimi K2.5)
        reasoning: str | None = None
        extracted_reasoning = _extract_reasoning_content(choice.message)
        if extracted_reasoning is not None:
            reasoning = extracted_reasoning

        if choice.message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments) if tc.function.arguments else {},
                )
                for tc in choice.message.tool_calls
            ]
            if reasoning is not None:
                yield (tool_calls, reasoning)
            else:
                yield tool_calls
