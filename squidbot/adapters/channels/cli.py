"""
Interactive CLI channel adapter.

Reads user input from stdin, sends responses to stdout.
Supports streaming output for a responsive feel.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from squidbot.core.models import InboundMessage, OutboundMessage, Session


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
                if text.lower() in ("exit", "quit", "/exit", "/quit", ":q"):
                    break
                if text:
                    yield InboundMessage(session=self.SESSION, text=text)
            except EOFError, KeyboardInterrupt:
                break

    def _prompt(self) -> str | None:
        """Blocking prompt — runs in a thread executor."""
        try:
            return input("\nYou: ")
        except EOFError:
            return None

    async def send(self, message: OutboundMessage) -> None:
        """Print the response to stdout."""
        print(message.text, end="", flush=True)

    async def send_typing(self, session_id: str) -> None:
        """No typing indicator for CLI."""
        pass
