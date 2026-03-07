"""Tests for dashboard streamed operator chat endpoint."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient

from squidbot.adapters.dashboard.api import build_dashboard_app
from squidbot.adapters.dashboard.chat import StreamingDashboardChannel, start_ndjson_stream
from squidbot.adapters.dashboard.logs import DashboardLogBuffer
from squidbot.adapters.dashboard.runtime import DashboardRuntime
from squidbot.config.schema import Settings
from squidbot.core.models import GatewayState, OutboundMessage, Session


def _runtime_with_config_and_loop(tmp_path, loop: Any) -> DashboardRuntime:
    config_path = tmp_path / "config.json"
    Settings().save(config_path)
    state = GatewayState(
        active_sessions={},
        channel_status=[],
        cron_jobs_cache=[],
        started_at=datetime(2026, 1, 1),
    )
    return DashboardRuntime(
        state=state,
        log_buffer=DashboardLogBuffer(),
        config_path=config_path,
        agent_loop=loop,
    )


def _headers(runtime: DashboardRuntime) -> dict[str, str]:
    return {
        "host": "localhost",
        "origin": "http://localhost",
        "x-squidbot-local-nonce": runtime.local_nonce,
    }


class ScriptedAgentLoop:
    """Agent loop double that emits fixed chunks."""

    async def run(self, session: Session, user_message: str, channel, **kwargs) -> None:  # type: ignore[no-untyped-def]
        assert session.channel == "dashboard"
        assert user_message == "hello"
        await channel.send(OutboundMessage(session=session, text="hi "))
        await channel.send(OutboundMessage(session=session, text="there"))


class ErrorAgentLoop:
    """Agent loop double that raises to test error frames."""

    async def run(self, session: Session, user_message: str, channel, **kwargs) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")


def test_chat_stream_emits_chunks_and_done(tmp_path) -> None:
    """Stream endpoint should emit chunk frames and terminal done frame."""
    runtime = _runtime_with_config_and_loop(tmp_path, ScriptedAgentLoop())
    client = TestClient(build_dashboard_app(runtime))

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"prompt": "hello"},
        headers=_headers(runtime),
    ) as response:
        lines = [line for line in response.iter_lines() if line]

    assert response.status_code == 200
    events = [json.loads(line) for line in lines]
    assert events[0] == {"type": "chunk", "text": "hi "}
    assert events[1] == {"type": "chunk", "text": "there"}
    assert events[-1] == {"type": "done"}


def test_chat_stream_emits_error_frame_on_failure(tmp_path) -> None:
    """Loop exceptions should be surfaced as terminal error frames."""
    runtime = _runtime_with_config_and_loop(tmp_path, ErrorAgentLoop())
    client = TestClient(build_dashboard_app(runtime))

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"prompt": "hello"},
        headers=_headers(runtime),
    ) as response:
        lines = [line for line in response.iter_lines() if line]

    assert response.status_code == 200
    events = [json.loads(line) for line in lines]
    assert events[0] == {"type": "error", "message": "internal error"}
    assert events[-1] == {"type": "done"}


async def test_start_ndjson_stream_cancels_producer_on_close() -> None:
    """Closing the stream iterator should cancel an active producer task."""
    cancelled = asyncio.Event()

    async def producer(frame_queue: asyncio.Queue[str | None]) -> None:
        await frame_queue.put('{"type":"chunk","text":"primed"}\n')
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    stream = start_ndjson_stream(producer)
    first = await anext(stream)
    assert json.loads(first) == {"type": "chunk", "text": "primed"}

    await stream.aclose()
    await asyncio.wait_for(cancelled.wait(), timeout=2.0)


async def test_start_ndjson_stream_ignores_producer_exception_on_close() -> None:
    """Closing stream should swallow producer failures during teardown."""

    async def producer(frame_queue: asyncio.Queue[str | None]) -> None:
        await frame_queue.put('{"type":"chunk","text":"primed"}\n')
        raise RuntimeError("boom")

    stream = start_ndjson_stream(producer)
    first = await anext(stream)

    assert json.loads(first) == {"type": "chunk", "text": "primed"}
    await stream.aclose()


async def test_streaming_dashboard_channel_send_typing_noop() -> None:
    """send_typing should be a harmless no-op for dashboard streams."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    channel = StreamingDashboardChannel(queue)

    await channel.send_typing(session_id="dashboard:local", typing=True)

    assert queue.empty()


def test_streaming_dashboard_channel_receive_not_supported() -> None:
    """Dashboard stream channel is send-only and rejects receive()."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    channel = StreamingDashboardChannel(queue)

    try:
        channel.receive()
    except NotImplementedError as exc:
        assert "does not support receive" in str(exc)
    else:
        raise AssertionError("receive() should raise NotImplementedError")
