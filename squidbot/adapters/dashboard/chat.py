"""Streaming primitives for dashboard operator chat transport.

This module bridges agent output chunks into NDJSON frames consumed by the
dashboard API response stream. It provides a queue-backed channel sink and a
stream wrapper that expose incremental assistant responses safely.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable

from squidbot.core.models import InboundMessage, OutboundMessage


class StreamingDashboardChannel:
    """ChannelPort-compatible sink that writes assistant chunks to a queue.

    Args:
        frame_queue: Queue used to emit NDJSON frame lines for streaming HTTP responses.
    """

    streaming = True

    def __init__(self, frame_queue: asyncio.Queue[str | None]) -> None:
        """Initialize the dashboard streaming channel.

        Args:
            frame_queue: Queue that receives NDJSON frame lines.

        Returns:
            None.
        """
        self._frame_queue = frame_queue

    def receive(self) -> AsyncIterator[InboundMessage]:
        """Reject receive because dashboard chat streaming is send-only.

        Returns:
            This method does not return and always raises NotImplementedError.
        """
        raise NotImplementedError("StreamingDashboardChannel does not support receive()")

    async def send(self, message: OutboundMessage) -> None:
        """Publish one assistant text chunk as an NDJSON frame line.

        Args:
            message: Outbound chunk produced by the assistant.

        Returns:
            None.
        """
        frame = json.dumps({"type": "chunk", "text": message.text})
        await self._frame_queue.put(f"{frame}\n")

    async def send_typing(self, session_id: str, typing: bool = True) -> None:
        """Ignore typing indicators for dashboard chat streams.

        Args:
            session_id: Session identifier for the typing event.
            typing: Whether typing started or stopped.

        Returns:
            None.
        """
        return None


def start_ndjson_stream(
    producer: Callable[[asyncio.Queue[str | None]], Awaitable[None]],
) -> AsyncGenerator[str]:
    """Run a producer and expose queued frames as an async NDJSON stream.

    Args:
        producer: Coroutine function that writes NDJSON frame lines to a queue.

    Returns:
        Async generator yielding NDJSON lines until producer completion or disconnect.
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
            try:
                await producer_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

    return _stream()
