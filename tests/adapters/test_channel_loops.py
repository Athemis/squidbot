"""Tests for CLI channel loop helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from squidbot.cli.main import GatewayState, _channel_loop, _channel_loop_with_state
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
    assert len(kwargs["extra_tools"]) == 1
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
    assert len(kwargs["extra_tools"]) == 1
    mock_tool_cls.assert_called_once_with(storage=storage)
