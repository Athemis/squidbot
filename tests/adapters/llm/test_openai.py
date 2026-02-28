from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from squidbot.adapters.llm.openai import OpenAIAdapter
from squidbot.core.models import Message


@pytest.mark.asyncio
async def test_openai_adapter_payload_gating() -> None:
    """Verify reasoning_content is included/omitted based on supports_reasoning_content."""
    # Test with supports_reasoning_content=False
    with patch("squidbot.adapters.llm.openai.AsyncOpenAI") as mock_openai:
        mock_client = mock_openai.return_value

        # Mock for _stream
        mock_stream = AsyncMock()
        mock_stream.__aenter__.return_value = AsyncMock()
        mock_stream.__aenter__.return_value.__aiter__.return_value = iter([])
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

        adapter = OpenAIAdapter(
            api_base="http://test",
            api_key="key",
            model="gpt-4",
            supports_reasoning_content=False,
        )

        messages = [Message(role="assistant", content="hi", reasoning_content="thinking")]

        # Consume the generator
        async for _ in await adapter.chat(messages, []):
            pass

        _, kwargs = mock_client.chat.completions.create.call_args
        sent_messages = kwargs["messages"]
        assert "reasoning_content" not in sent_messages[0]

    # Test with supports_reasoning_content=True
    with patch("squidbot.adapters.llm.openai.AsyncOpenAI") as mock_openai:
        mock_client = mock_openai.return_value

        mock_stream = AsyncMock()
        mock_stream.__aenter__.return_value = AsyncMock()
        mock_stream.__aenter__.return_value.__aiter__.return_value = iter([])
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

        adapter = OpenAIAdapter(
            api_base="http://test",
            api_key="key",
            model="gpt-4",
            supports_reasoning_content=True,
        )

        messages = [Message(role="assistant", content="hi", reasoning_content="thinking")]

        async for _ in await adapter.chat(messages, []):
            pass

        _, kwargs = mock_client.chat.completions.create.call_args
        sent_messages = kwargs["messages"]
        assert sent_messages[0]["reasoning_content"] == "thinking"


@pytest.mark.asyncio
async def test_openai_adapter_payload_gating_non_streaming() -> None:
    """Verify reasoning_content gating in non-streaming mode."""
    with patch("squidbot.adapters.llm.openai.AsyncOpenAI") as mock_openai:
        mock_client = mock_openai.return_value

        # Mock for _complete
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "hello"
        mock_choice.message.tool_calls = None
        mock_choice.message.reasoning_content = None
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        adapter = OpenAIAdapter(
            api_base="http://test",
            api_key="key",
            model="gpt-4",
            supports_reasoning_content=True,
        )

        messages = [Message(role="assistant", content="hi", reasoning_content="thinking")]

        async for _ in await adapter.chat(messages, [], stream=False):
            pass

        _, kwargs = mock_client.chat.completions.create.call_args
        sent_messages = kwargs["messages"]
        assert sent_messages[0]["reasoning_content"] == "thinking"


@pytest.mark.asyncio
async def test_openai_adapter_empty_reasoning_preserved() -> None:
    """Verify empty reasoning_content is preserved in the payload."""
    with patch("squidbot.adapters.llm.openai.AsyncOpenAI") as mock_openai:
        mock_client = mock_openai.return_value

        mock_stream = AsyncMock()
        mock_stream.__aenter__.return_value = AsyncMock()
        mock_stream.__aenter__.return_value.__aiter__.return_value = iter([])
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

        adapter = OpenAIAdapter(
            api_base="http://test",
            api_key="key",
            model="gpt-4",
            supports_reasoning_content=True,
        )

        messages = [Message(role="assistant", content="hi", reasoning_content="")]

        async for _ in await adapter.chat(messages, []):
            pass

        _, kwargs = mock_client.chat.completions.create.call_args
        sent_messages = kwargs["messages"]
        assert sent_messages[0]["reasoning_content"] == ""


@pytest.mark.asyncio
async def test_openai_adapter_stream_reads_reasoning_from_model_extra() -> None:
    with patch("squidbot.adapters.llm.openai.AsyncOpenAI") as mock_openai:
        mock_client = mock_openai.return_value

        delta = MagicMock()
        delta.content = None
        delta.tool_calls = [
            MagicMock(
                index=0,
                id="tc_1",
                function=MagicMock(name="echo", arguments='{"text":"hi"}'),
            )
        ]
        delta.model_extra = {"reasoning_content": "reasoning via model_extra"}
        delta.reasoning_content = None

        chunk = MagicMock()
        chunk.choices = [MagicMock(delta=delta)]

        mock_stream = AsyncMock()
        mock_stream.__aenter__.return_value = AsyncMock()
        mock_stream.__aenter__.return_value.__aiter__.return_value = iter([chunk])
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

        adapter = OpenAIAdapter(
            api_base="http://test",
            api_key="key",
            model="gpt-4",
            supports_reasoning_content=True,
        )

        events: list[object] = []
        async for event in await adapter.chat([Message(role="user", content="hi")], []):
            events.append(event)

        assert events
        assert isinstance(events[-1], tuple)
        tool_calls, reasoning = events[-1]
        assert reasoning == "reasoning via model_extra"
        assert tool_calls[0].id == "tc_1"


@pytest.mark.asyncio
async def test_openai_adapter_complete_reads_reasoning_from_model_extra() -> None:
    with patch("squidbot.adapters.llm.openai.AsyncOpenAI") as mock_openai:
        mock_client = mock_openai.return_value

        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_choice.message.tool_calls = [
            MagicMock(id="tc_1", function=MagicMock(name="echo", arguments='{"text":"hi"}'))
        ]
        mock_choice.message.reasoning_content = None
        mock_choice.message.model_extra = {"reasoning_content": "reasoning via model_extra"}
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        adapter = OpenAIAdapter(
            api_base="http://test",
            api_key="key",
            model="gpt-4",
            supports_reasoning_content=True,
        )

        events: list[object] = []
        async for event in await adapter.chat(
            [Message(role="user", content="hi")], [], stream=False
        ):
            events.append(event)

        assert events
        assert isinstance(events[-1], tuple)
        tool_calls, reasoning = events[-1]
        assert reasoning == "reasoning via model_extra"
        assert tool_calls[0].id == "tc_1"
