"""
Sub-agent spawn tool for squidbot.

Provides SpawnTool and SpawnAwaitTool, enabling a parent agent to delegate
tasks to isolated sub-agents running as concurrent asyncio Tasks.
Sub-agents are configured via named profiles in squidbot.yaml, or inherit
the parent's context when no profile is specified.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from squidbot.core.models import InboundMessage, OutboundMessage


class CollectingChannel:
    """
    Non-streaming channel used by sub-agents to collect their output.

    Sub-agents write their final response via send(); the result is
    retrieved via the collected_text property.
    """

    streaming: bool = False

    def __init__(self) -> None:
        """Initialise with empty buffer."""
        self._parts: list[str] = []

    async def send(self, message: OutboundMessage) -> None:
        """Append message text to the internal buffer."""
        self._parts.append(message.text)

    async def send_typing(self, session_id: str) -> None:
        """No-op — sub-agents do not send typing indicators."""

    def receive(self) -> AsyncIterator[InboundMessage]:
        """Return an async iterator that immediately exhausts."""
        return _empty_iter()

    @property
    def collected_text(self) -> str:
        """Return all collected text joined."""
        return "".join(self._parts)


async def _empty_iter() -> AsyncIterator[InboundMessage]:
    """Async generator that yields nothing."""
    return
    yield  # makes this an async generator
