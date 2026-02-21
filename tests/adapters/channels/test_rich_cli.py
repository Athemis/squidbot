"""Tests for RichCliChannel."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.markdown import Markdown

from squidbot.adapters.channels.cli import RichCliChannel
from squidbot.core.models import OutboundMessage, Session


class TestRichCliChannelAttributes:
    def test_streaming_is_false(self):
        """RichCliChannel must not stream — Markdown needs the full text."""
        ch = RichCliChannel()
        assert ch.streaming is False

    def test_session_is_cli_local(self):
        ch = RichCliChannel()
        assert ch.SESSION == Session(channel="cli", sender_id="local")


class TestRichCliChannelSend:
    @pytest.mark.asyncio
    async def test_send_prints_to_console(self):
        """send() should render response as Markdown via Console.print."""
        ch = RichCliChannel()
        msg = OutboundMessage(session=Session(channel="cli", sender_id="local"), text="**hello**")

        with patch("squidbot.adapters.channels.cli.Console") as MockConsole:
            mock_console = MagicMock()
            MockConsole.return_value = mock_console

            await ch.send(msg)

            mock_console.print.assert_called()
            # At least one call should have passed a Markdown object
            calls = mock_console.print.call_args_list
            assert any(isinstance(arg, Markdown) for call in calls for arg in call.args), (
                "Expected Console.print to be called with a Markdown object"
            )

    @pytest.mark.asyncio
    async def test_send_typing_is_noop(self):
        """send_typing() should not raise."""
        ch = RichCliChannel()
        await ch.send_typing("cli:local")  # Should not raise


class TestRichCliChannelReceive:
    @pytest.mark.asyncio
    async def test_receive_yields_inbound_message(self):
        """receive() should yield an InboundMessage for non-empty, non-exit input."""
        ch = RichCliChannel()

        with patch(
            "squidbot.adapters.channels.cli.asyncio.to_thread", new_callable=AsyncMock
        ) as mock_thread:
            # First call returns a message, second raises EOFError to end the loop
            mock_thread.side_effect = ["Hello world", EOFError()]

            messages = []
            async for msg in ch.receive():
                messages.append(msg)

        assert len(messages) == 1
        assert messages[0].text == "Hello world"

    @pytest.mark.asyncio
    async def test_receive_skips_empty_input(self):
        """receive() should skip blank lines."""
        ch = RichCliChannel()

        with patch(
            "squidbot.adapters.channels.cli.asyncio.to_thread", new_callable=AsyncMock
        ) as mock_thread:
            mock_thread.side_effect = ["   ", "Hi", EOFError()]

            messages = []
            async for msg in ch.receive():
                messages.append(msg)

        assert len(messages) == 1
        assert messages[0].text == "Hi"

    @pytest.mark.asyncio
    async def test_receive_stops_on_exit(self):
        """receive() should stop when user types 'exit'."""
        ch = RichCliChannel()

        with patch(
            "squidbot.adapters.channels.cli.asyncio.to_thread", new_callable=AsyncMock
        ) as mock_thread:
            mock_thread.side_effect = ["exit"]

            messages = []
            async for msg in ch.receive():
                messages.append(msg)

        assert messages == []

    @pytest.mark.asyncio
    async def test_receive_stops_on_quit(self):
        """receive() should stop when user types 'quit'."""
        ch = RichCliChannel()

        with patch(
            "squidbot.adapters.channels.cli.asyncio.to_thread", new_callable=AsyncMock
        ) as mock_thread:
            mock_thread.side_effect = ["quit"]

            messages = []
            async for msg in ch.receive():
                messages.append(msg)

        assert messages == []
