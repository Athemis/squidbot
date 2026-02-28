"""
Interactive CLI channel adapter.

Reads user input from stdin, sends responses to stdout.
Supports streaming output for a responsive feel.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule

from squidbot.core.models import InboundMessage, OutboundMessage, Session

EXIT_COMMANDS = ("exit", "quit", "/exit", "/quit", ":q")


class CliChannel:
    """
    CLI channel for interactive terminal use.

    The receive() method prompts for user input; send() prints to stdout.
    This adapter runs in a single session: "cli:local".
    """

    SESSION = Session(channel="cli", sender_id="local")
    streaming = True  # stream text chunks to stdout as they arrive

    async def receive(self) -> AsyncIterator[InboundMessage]:
        """Yield messages from stdin, one per line."""
        while True:
            try:
                line = await asyncio.to_thread(self._prompt)
                if line is None:
                    break
                text = line.strip()
                if text.lower() in EXIT_COMMANDS:
                    break
                if text:
                    yield InboundMessage(session=self.SESSION, text=text)
            except EOFError, KeyboardInterrupt:
                break

    def _prompt(self) -> str | None:
        """Blocking prompt — runs in a thread executor."""
        try:
            return input("\nYou: ")
        except EOFError, KeyboardInterrupt:
            return None

    async def send(self, message: OutboundMessage) -> None:
        """Print the response to stdout."""
        print(message.text, end="", flush=True)

    async def send_typing(self, session_id: str) -> None:
        """No typing indicator for CLI."""
        pass


class RichCliChannel:
    """
    Rich-rendered CLI channel for interactive terminal use.

    Uses Rich for Markdown rendering and coloured prompts.
    Collects full response before printing (streaming=False).
    """

    SESSION = Session(channel="cli", sender_id="local")
    streaming = False  # collect all chunks before calling send()

    def __init__(self) -> None:
        """Initialize Rich CLI state."""
        self._session: PromptSession[str] | None = None

    def _get_session(self) -> PromptSession[str]:
        """Create and cache the prompt-toolkit session."""
        if self._session is None:
            self._session = PromptSession(
                message=FormattedText([("class:prompt", "\nYou: ")]),
                style=Style.from_dict({"prompt": "bold ansigreen"}),
            )
        return self._session

    async def receive(self) -> AsyncIterator[InboundMessage]:
        """Yield messages from stdin using prompt-toolkit input."""
        while True:
            try:
                with patch_stdout():
                    text = (await self._get_session().prompt_async()).strip()
                if text.lower() in EXIT_COMMANDS:
                    break
                if text:
                    yield InboundMessage(session=self.SESSION, text=text)
            except EOFError, KeyboardInterrupt:
                break

    async def send(self, message: OutboundMessage) -> None:
        """Print the response as Markdown via Rich Console."""
        console = Console()
        console.print(Rule(style="dim"))
        console.print("[bold cyan]squidbot ›[/bold cyan]")
        console.print(Markdown(message.text))

    async def send_typing(self, session_id: str) -> None:
        """No typing indicator for Rich CLI."""
        pass
