"""Tests for squidbot.cli.gateway module.

Covers the performance-sensitive helpers introduced in the perf/performance-optimization
branch: concurrent MCP server connection startup (_connect_mcp_servers) and the
singleton MemoryWriteTool lifecycle that avoids re-instantiation on every message.
All tests use in-process test doubles; no real MCP servers or filesystem state is needed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock


async def test_mcp_servers_connect_in_parallel() -> None:
    """Multiple MCP server connections must be established concurrently."""
    import asyncio
    import time
    from unittest.mock import MagicMock

    connect_starts: list[float] = []

    async def slow_connect() -> list:
        connect_starts.append(time.monotonic())
        await asyncio.sleep(0.05)
        return []

    conn1: MagicMock = MagicMock()
    conn2: MagicMock = MagicMock()
    conn1.connect = slow_connect
    conn2.connect = slow_connect

    from squidbot.cli.gateway import _connect_mcp_servers

    start = time.monotonic()
    await _connect_mcp_servers([conn1, conn2])
    elapsed = time.monotonic() - start

    assert elapsed < 0.09, f"MCP servers connected sequentially (elapsed={elapsed:.3f}s)"
    assert len(connect_starts) == 2
    assert abs(connect_starts[1] - connect_starts[0]) < 0.025


async def test_memory_write_tool_is_singleton_across_messages(tmp_path: Path) -> None:
    """MemoryWriteTool must be reused across messages, not re-instantiated each time."""
    from collections.abc import AsyncIterator
    from unittest.mock import AsyncMock, MagicMock, patch

    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.cli.gateway import _channel_loop
    from squidbot.core.models import InboundMessage, OutboundMessage, Session

    class TwoMessageChannel:
        streaming = False

        async def receive(self) -> AsyncIterator[InboundMessage]:
            session = Session(channel="cli", sender_id="local")
            yield InboundMessage(session=session, text="msg1")
            yield InboundMessage(session=session, text="msg2")

        async def send(self, message: OutboundMessage) -> None: ...

        async def send_typing(self, session_id: str, typing: bool = True) -> None: ...

    fake_loop = AsyncMock()
    storage = JsonlMemory(base_dir=tmp_path)

    mock_cls = MagicMock(return_value=MagicMock())

    with patch("squidbot.adapters.tools.memory_write.MemoryWriteTool", mock_cls):
        await _channel_loop(
            channel=TwoMessageChannel(),  # type: ignore[arg-type]
            loop=fake_loop,
            storage=storage,
        )

    assert mock_cls.call_count == 1, (
        f"MemoryWriteTool was instantiated {mock_cls.call_count} times for 2 messages"
    )


async def test_channel_loop_forwards_user_sender_id_from_metadata(tmp_path: Path) -> None:
    """_channel_loop forwards matrix_sender_id for room-scoped Matrix sessions."""
    from collections.abc import AsyncIterator

    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.cli.gateway import _channel_loop
    from squidbot.core.models import InboundMessage, OutboundMessage, Session

    class OneMessageChannel:
        streaming = False

        async def receive(self) -> AsyncIterator[InboundMessage]:
            session = Session(channel="matrix", sender_id="!room1:example.org")
            metadata = {
                "matrix_room_id": "!room1:example.org",
                "matrix_sender_id": "@alice:example.org",
            }
            yield InboundMessage(session=session, text="msg1", metadata=metadata)

        async def send(self, message: OutboundMessage) -> None: ...

        async def send_typing(self, session_id: str, typing: bool = True) -> None: ...

    fake_loop = AsyncMock()
    storage = JsonlMemory(base_dir=tmp_path)

    await _channel_loop(
        channel=OneMessageChannel(),  # type: ignore[arg-type]
        loop=fake_loop,
        storage=storage,
    )

    assert fake_loop.run.await_count == 1
    assert fake_loop.run.await_args.kwargs.get("user_sender_id") == "@alice:example.org"


async def test_mcp_server_that_raises_is_skipped() -> None:
    """A connection whose connect() raises must be skipped (not propagated) with a warning."""
    from unittest.mock import MagicMock

    from squidbot.cli.gateway import _connect_mcp_servers

    async def failing_connect() -> list:
        raise RuntimeError("connection failed")

    async def good_connect() -> list:
        return []

    conn_fail: MagicMock = MagicMock()
    conn_ok: MagicMock = MagicMock()
    conn_fail.connect = failing_connect
    conn_ok.connect = good_connect

    result = await _connect_mcp_servers([conn_fail, conn_ok])

    # Only the successful connection must appear in the result.
    assert len(result) == 1
    assert result[0][0] is conn_ok
