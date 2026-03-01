"""Tests for CLI channel loop helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from squidbot.cli.gateway import GatewayState, _channel_loop, _channel_loop_with_state
from squidbot.core.models import InboundMessage, Session


def _make_fake_channel(session_id: str = "s1", text: str = "hello") -> MagicMock:
    """Return a channel that yields one InboundMessage then stops."""
    inbound = InboundMessage(
        session=Session(channel="matrix", sender_id=session_id),
        text=text,
    )

    async def _receive():
        yield inbound

    channel = MagicMock()
    channel.receive = _receive
    return channel


def _make_fake_channel_with_metadata() -> MagicMock:
    """Return a channel yielding one message with Matrix metadata."""
    inbound = InboundMessage(
        session=Session(channel="matrix", sender_id="@alice:example.org"),
        text="decrypted encrypted message",
        metadata={"matrix_room_id": "!room1:example.org", "matrix_event_id": "$evt1"},
    )

    async def _receive():
        yield inbound

    channel = MagicMock()
    channel.receive = _receive
    return channel


async def test_channel_loop_with_state_passes_extra_tools():
    """_channel_loop_with_state must call loop.run with a non-empty extra_tools list."""
    storage = MagicMock()
    loop = MagicMock()
    loop.run = AsyncMock()
    state = GatewayState(active_sessions={}, channel_status=[], cron_jobs_cache=[])
    channel = _make_fake_channel()

    with patch("squidbot.adapters.tools.memory_write.MemoryWriteTool") as mock_tool_cls:
        mock_tool_cls.return_value = MagicMock()
        await _channel_loop_with_state(channel, loop, state, storage)

    loop.run.assert_awaited_once()
    _, kwargs = loop.run.call_args
    assert "extra_tools" in kwargs
    assert len(kwargs["extra_tools"]) == 2
    assert any(getattr(t, "name", None) == "cron_add" for t in kwargs["extra_tools"])
    mock_tool_cls.assert_called_once_with(storage=storage)


async def test_channel_loop_passes_extra_tools():
    """_channel_loop must call loop.run with a non-empty extra_tools list."""
    storage = MagicMock()
    loop = MagicMock()
    loop.run = AsyncMock()
    channel = _make_fake_channel()

    with patch("squidbot.adapters.tools.memory_write.MemoryWriteTool") as mock_tool_cls:
        mock_tool_cls.return_value = MagicMock()
        await _channel_loop(channel, loop, storage)

    loop.run.assert_awaited_once()
    _, kwargs = loop.run.call_args
    assert "extra_tools" in kwargs
    assert len(kwargs["extra_tools"]) == 2
    assert any(getattr(t, "name", None) == "cron_add" for t in kwargs["extra_tools"])
    mock_tool_cls.assert_called_once_with(storage=storage)


async def test_channel_loop_with_state_forwards_metadata_to_agent_loop() -> None:
    """_channel_loop_with_state forwards inbound metadata to AgentLoop.run()."""
    storage = MagicMock()
    loop = MagicMock()
    loop.run = AsyncMock()
    state = GatewayState(active_sessions={}, channel_status=[], cron_jobs_cache=[])
    channel = _make_fake_channel_with_metadata()

    await _channel_loop_with_state(channel, loop, state, storage)

    loop.run.assert_awaited_once()
    args, kwargs = loop.run.call_args
    assert args[0].channel == "matrix"
    assert args[0].sender_id == "@alice:example.org"
    assert args[1] == "decrypted encrypted message"
    assert kwargs["outbound_metadata"] == {
        "matrix_room_id": "!room1:example.org",
        "matrix_event_id": "$evt1",
    }


def _make_multimodal_channel(
    session_id: str = "@alice:example.org",
) -> tuple[MagicMock, list[dict[str, Any]]]:
    """Return a channel that yields one InboundMessage with multimodal_content."""
    multimodal: list[dict[str, Any]] = [
        {"type": "text", "text": "what is in this image?"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}},
    ]
    inbound = InboundMessage(
        session=Session(channel="matrix", sender_id=session_id),
        text="what is in this image?",
        multimodal_content=multimodal,
    )

    async def _receive():
        yield inbound

    channel = MagicMock()
    channel.receive = _receive
    return channel, multimodal


async def test_channel_loop_with_state_passes_multimodal_content_to_agent_loop() -> None:
    """When InboundMessage.multimodal_content is set, gateway passes the list to loop.run()."""
    storage = MagicMock()
    loop = MagicMock()
    loop.run = AsyncMock()
    state = GatewayState(active_sessions={}, channel_status=[], cron_jobs_cache=[])
    channel, expected_multimodal = _make_multimodal_channel()

    await _channel_loop_with_state(channel, loop, state, storage)

    loop.run.assert_awaited_once()
    args, _ = loop.run.call_args
    assert args[1] == expected_multimodal, (
        f"Expected multimodal list to be passed to loop.run(), got: {args[1]!r}"
    )


async def test_channel_loop_with_state_falls_back_to_text_when_no_multimodal() -> None:
    """When multimodal_content is None, gateway passes text string to loop.run()."""
    storage = MagicMock()
    loop = MagicMock()
    loop.run = AsyncMock()
    state = GatewayState(active_sessions={}, channel_status=[], cron_jobs_cache=[])
    channel = _make_fake_channel(text="plain text message")

    await _channel_loop_with_state(channel, loop, state, storage)

    args, _ = loop.run.call_args
    assert args[1] == "plain text message"


async def test_channel_loop_passes_multimodal_content_to_agent_loop() -> None:
    """_channel_loop also forwards multimodal content when present."""
    storage = MagicMock()
    loop = MagicMock()
    loop.run = AsyncMock()
    channel, expected_multimodal = _make_multimodal_channel()

    await _channel_loop(channel, loop, storage)

    loop.run.assert_awaited_once()
    args, _ = loop.run.call_args
    assert args[1] == expected_multimodal


async def test_channel_loop_falls_back_to_text_when_no_multimodal() -> None:
    """_channel_loop passes plain text when multimodal_content is None."""
    storage = MagicMock()
    loop = MagicMock()
    loop.run = AsyncMock()
    channel = _make_fake_channel(text="just text")

    await _channel_loop(channel, loop, storage)

    args, _ = loop.run.call_args
    assert args[1] == "just text"
