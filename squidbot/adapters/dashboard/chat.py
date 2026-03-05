"""Streaming channel adapter used by dashboard operator chat endpoint."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import suppress

from squidbot.core.models import InboundMessage, OutboundMessage


class StreamingDashboardChannel:
    """ChannelPort-compatible sink that writes assistant chunks to a queue."""

    streaming = True

    def __init__(self, frame_queue: asyncio.Queue[str | None]) -> None:
        """Initialize with a queue that receives NDJSON frame lines."""
        self._frame_queue = frame_queue

    def receive(self) -> AsyncIterator[InboundMessage]:
        """Dashboard chat endpoint is send-only and does not receive messages."""
        raise NotImplementedError("StreamingDashboardChannel does not support receive()")

    async def send(self, message: OutboundMessage) -> None:
        """Publish one assistant chunk as a frame line."""
        frame = json.dumps({"type": "chunk", "text": message.text})
        await self._frame_queue.put(f"{frame}\n")

    async def send_typing(self, session_id: str, typing: bool = True) -> None:
        """Typing indicators are ignored for dashboard chat streams."""
        return None


def start_ndjson_stream(
    producer: Callable[[asyncio.Queue[str | None]], Awaitable[None]],
) -> AsyncGenerator[str]:
    """Run a producer and expose queue frames as an async NDJSON stream.

    The stream cancels the producer task when the consumer disconnects.
    """

    frame_queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _wrapped_producer() -> None:
        try:
            await producer(frame_queue)
        finally:
            await frame_queue.put('{"type":"done"}\n')
            await frame_queue.put(None)

    producer_task = asyncio.create_task(_wrapped_producer())

    async def _stream() -> AsyncGenerator[str]:
        try:
            while True:
                item = await frame_queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not producer_task.done():
                producer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await producer_task

    return _stream()
