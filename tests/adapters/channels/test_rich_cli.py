"""Tests for RichCliChannel."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.markdown import Markdown  # pyright: ignore[reportMissingImports]

from squidbot.adapters.channels.cli import RichCliChannel
from squidbot.core.models import OutboundMessage, Session


class TestRichCliChannelAttributes:
    def test_streaming_is_false(self):
        """RichCliChannel must not stream — Markdown needs the full text."""
        ch = RichCliChannel()
        assert ch.streaming is False

    def test_session_is_cli_local(self):
        ch = RichCliChannel()
        assert Session(channel="cli", sender_id="local") == ch.SESSION


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

        with patch("squidbot.adapters.channels.cli.PromptSession") as mock_prompt_session_class:
            mock_prompt_session = MagicMock()
            mock_prompt_session.prompt_async = AsyncMock(side_effect=["Hello world", EOFError()])
            mock_prompt_session_class.return_value = mock_prompt_session

            messages = []
            async for msg in ch.receive():
                messages.append(msg)

        assert len(messages) == 1
        assert messages[0].text == "Hello world"

    @pytest.mark.asyncio
    async def test_receive_skips_empty_input(self):
        """receive() should skip blank lines."""
        ch = RichCliChannel()

        with patch("squidbot.adapters.channels.cli.PromptSession") as mock_prompt_session_class:
            mock_prompt_session = MagicMock()
            mock_prompt_session.prompt_async = AsyncMock(side_effect=["   ", "Hi", EOFError()])
            mock_prompt_session_class.return_value = mock_prompt_session

            messages = []
            async for msg in ch.receive():
                messages.append(msg)

        assert len(messages) == 1
        assert messages[0].text == "Hi"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("command", ["exit", "quit", "/exit", "/quit", ":q"])
    async def test_receive_stops_on_exit_variants(self, command: str):
        """receive() should stop for all configured exit commands."""
        ch = RichCliChannel()

        with patch("squidbot.adapters.channels.cli.PromptSession") as mock_prompt_session_class:
            mock_prompt_session = MagicMock()
            mock_prompt_session.prompt_async = AsyncMock(side_effect=[command])
            mock_prompt_session_class.return_value = mock_prompt_session

            messages = []
            async for msg in ch.receive():
                messages.append(msg)

        assert messages == []

    @pytest.mark.asyncio
    async def test_receive_stops_on_keyboard_interrupt(self):
        """receive() should stop when prompt input is interrupted."""
        ch = RichCliChannel()

        with patch("squidbot.adapters.channels.cli.PromptSession") as mock_prompt_session_class:
            mock_prompt_session = MagicMock()
            mock_prompt_session.prompt_async = AsyncMock(side_effect=[KeyboardInterrupt()])
            mock_prompt_session_class.return_value = mock_prompt_session

            messages = []
            async for msg in ch.receive():
                messages.append(msg)

        assert messages == []

    @pytest.mark.asyncio
    async def test_receive_uses_patch_stdout(self):
        """receive() should prompt within prompt-toolkit patch_stdout()."""
        ch = RichCliChannel()

        with (
            patch("squidbot.adapters.channels.cli.PromptSession") as mock_prompt_session_class,
            patch("squidbot.adapters.channels.cli.patch_stdout") as mock_patch_stdout,
        ):
            mock_prompt_session = MagicMock()
            mock_prompt_session.prompt_async = AsyncMock(side_effect=["Hello", EOFError()])
            mock_prompt_session_class.return_value = mock_prompt_session

            messages = []
            async for msg in ch.receive():
                messages.append(msg)

        assert len(messages) == 1
        assert messages[0].text == "Hello"
        assert mock_patch_stdout.called
        mock_patch_stdout.return_value.__enter__.assert_called()
        mock_patch_stdout.return_value.__exit__.assert_called()
