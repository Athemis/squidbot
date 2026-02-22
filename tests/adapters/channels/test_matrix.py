"""Tests for MatrixChannel — receiving messages."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from squidbot.config.schema import MatrixChannelConfig

# These imports will fail until MatrixChannel is implemented — that's expected.
# from squidbot.adapters.channels.matrix import MatrixChannel


def _make_config(**kwargs: object) -> MatrixChannelConfig:
    defaults = {
        "enabled": True,
        "homeserver": "https://matrix.example.org",
        "user_id": "@bot:example.org",
        "access_token": "syt_test",
        "device_id": "TEST",
        "room_ids": ["!room1:example.org"],
        "group_policy": "open",
        "allowlist": [],
    }
    defaults.update(kwargs)
    return MatrixChannelConfig(**defaults)


class TestMatrixChannelReceive:
    """MatrixChannel.receive() yields InboundMessage for accepted events."""

    @pytest.fixture
    def fake_nio(self) -> MagicMock:
        """Return a mock nio.AsyncClient."""
        client = MagicMock()
        client.login = AsyncMock(return_value=MagicMock(access_token="syt_test"))
        client.sync_forever = AsyncMock()
        client.add_event_callback = MagicMock()
        client.close = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_open_policy_accepts_any_message(self, fake_nio: MagicMock) -> None:
        """With group_policy=open, any message in the room is accepted."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="open")
        ch = MatrixChannel(config=config)

        # Simulate a text event arriving
        event = MagicMock()
        event.sender = "@alice:example.org"
        event.room_id = "!room1:example.org"
        event.event_id = "$evt1"
        event.body = "hello bot"
        event.source = {"content": {}}
        event.server_timestamp = int(datetime.now().timestamp() * 1000)

        with patch("squidbot.adapters.channels.matrix.nio.AsyncClient", return_value=fake_nio):
            await ch._handle_text(MagicMock(), event)

        msgs = []
        async for msg in ch.receive():
            msgs.append(msg)
            break  # one message is enough

        assert len(msgs) == 1
        assert msgs[0].text == "hello bot"
        assert msgs[0].session.sender_id == "@alice:example.org"

    @pytest.mark.asyncio
    async def test_open_policy_skips_own_messages(self, fake_nio: MagicMock) -> None:
        """Own messages (sender == bot user_id) are never yielded."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="open")
        ch = MatrixChannel(config=config)

        event = MagicMock()
        event.sender = "@bot:example.org"  # same as config.user_id
        event.room_id = "!room1:example.org"
        event.event_id = "$evt2"
        event.body = "my own message"
        event.source = {"content": {}}
        event.server_timestamp = int(datetime.now().timestamp() * 1000)

        await ch._handle_text(MagicMock(), event)

        # Queue should be empty
        assert ch._queue.empty()

    @pytest.mark.asyncio
    async def test_mention_policy_accepts_mention(self, fake_nio: MagicMock) -> None:
        """With group_policy=mention, message is accepted if user_id appears in body."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="mention")
        ch = MatrixChannel(config=config)

        event = MagicMock()
        event.sender = "@alice:example.org"
        event.room_id = "!room1:example.org"
        event.event_id = "$evt3"
        event.body = "hey @bot:example.org can you help?"
        event.source = {"content": {}}
        event.server_timestamp = int(datetime.now().timestamp() * 1000)

        await ch._handle_text(MagicMock(), event)

        assert not ch._queue.empty()

    @pytest.mark.asyncio
    async def test_mention_policy_ignores_without_mention(self, fake_nio: MagicMock) -> None:
        """With group_policy=mention, message without bot mention is ignored."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="mention")
        ch = MatrixChannel(config=config)

        event = MagicMock()
        event.sender = "@alice:example.org"
        event.room_id = "!room1:example.org"
        event.event_id = "$evt4"
        event.body = "talking to myself"
        event.source = {"content": {}}
        event.server_timestamp = int(datetime.now().timestamp() * 1000)

        await ch._handle_text(MagicMock(), event)

        assert ch._queue.empty()

    @pytest.mark.asyncio
    async def test_allowlist_policy_accepts_listed_sender(self, fake_nio: MagicMock) -> None:
        """With group_policy=allowlist, only senders in allowlist are accepted."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="allowlist", allowlist=["@alice:example.org"])
        ch = MatrixChannel(config=config)

        event = MagicMock()
        event.sender = "@alice:example.org"
        event.room_id = "!room1:example.org"
        event.event_id = "$evt5"
        event.body = "hello"
        event.source = {"content": {}}
        event.server_timestamp = int(datetime.now().timestamp() * 1000)

        await ch._handle_text(MagicMock(), event)

        assert not ch._queue.empty()

    @pytest.mark.asyncio
    async def test_allowlist_policy_ignores_unlisted_sender(self, fake_nio: MagicMock) -> None:
        """With group_policy=allowlist, senders not in allowlist are dropped."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="allowlist", allowlist=["@alice:example.org"])
        ch = MatrixChannel(config=config)

        event = MagicMock()
        event.sender = "@mallory:example.org"
        event.room_id = "!room1:example.org"
        event.event_id = "$evt6"
        event.body = "hello"
        event.source = {"content": {}}
        event.server_timestamp = int(datetime.now().timestamp() * 1000)

        await ch._handle_text(MagicMock(), event)

        assert ch._queue.empty()

    @pytest.mark.asyncio
    async def test_thread_root_extracted_into_metadata(self, fake_nio: MagicMock) -> None:
        """Thread root event_id is stored in InboundMessage.metadata."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="open")
        ch = MatrixChannel(config=config)

        event = MagicMock()
        event.sender = "@alice:example.org"
        event.room_id = "!room1:example.org"
        event.event_id = "$reply1"
        event.body = "reply in thread"
        event.source = {
            "content": {
                "m.relates_to": {
                    "rel_type": "m.thread",
                    "event_id": "$thread_root_123",
                }
            }
        }
        event.server_timestamp = int(datetime.now().timestamp() * 1000)

        await ch._handle_text(MagicMock(), event)

        assert not ch._queue.empty()
        msg = ch._queue.get_nowait()
        assert msg.metadata["matrix_thread_root"] == "$thread_root_123"
        assert msg.metadata["matrix_event_id"] == "$reply1"
        assert msg.metadata["matrix_room_id"] == "!room1:example.org"


class TestMatrixChannelTyping:
    """MatrixChannel.send_typing() manages the keepalive loop correctly."""

    @pytest.mark.asyncio
    async def test_send_typing_true_starts_task(self) -> None:
        """send_typing(True) creates a background keepalive task."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        ch._client.room_typing = AsyncMock(return_value=MagicMock())

        # Seed the session_rooms so send_typing can find the room
        ch._session_rooms["matrix:@alice:example.org"] = "!room1:example.org"

        await ch.send_typing("matrix:@alice:example.org", typing=True)
        await asyncio.sleep(0)  # let the event loop tick

        assert "!room1:example.org" in ch._typing_tasks
        assert not ch._typing_tasks["!room1:example.org"].done()

        # Cleanup
        await ch.send_typing("matrix:@alice:example.org", typing=False)

    @pytest.mark.asyncio
    async def test_send_typing_false_cancels_task_and_sends_stop(self) -> None:
        """send_typing(False) cancels the keepalive task and sends stop event."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)
        stop_calls: list[tuple[str, bool]] = []

        async def fake_room_typing(room_id: str, typing_state: bool, timeout: int = 0) -> MagicMock:
            stop_calls.append((room_id, typing_state))
            return MagicMock()

        ch._client = MagicMock()
        ch._client.room_typing = fake_room_typing
        ch._session_rooms["matrix:@alice:example.org"] = "!room1:example.org"

        await ch.send_typing("matrix:@alice:example.org", typing=True)
        await asyncio.sleep(0)
        await ch.send_typing("matrix:@alice:example.org", typing=False)
        await asyncio.sleep(0)

        # The stop call (typing_state=False) must have been sent
        assert any(room == "!room1:example.org" and state is False for room, state in stop_calls)
        assert "!room1:example.org" not in ch._typing_tasks

    @pytest.mark.asyncio
    async def test_typing_keepalive_resends_after_interval(self) -> None:
        """Keepalive loop calls room_typing again after TYPING_KEEPALIVE_S."""
        from squidbot.adapters.channels import matrix as matrix_mod
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)
        call_count = 0

        async def fake_room_typing(room_id: str, typing_state: bool, timeout: int = 0) -> MagicMock:
            nonlocal call_count
            if typing_state:
                call_count += 1
            return MagicMock()

        ch._client = MagicMock()
        ch._client.room_typing = fake_room_typing
        ch._session_rooms["matrix:@alice:example.org"] = "!room1:example.org"

        original = matrix_mod._TYPING_KEEPALIVE_S
        matrix_mod._TYPING_KEEPALIVE_S = 0.05  # speed up test

        try:
            await ch.send_typing("matrix:@alice:example.org", typing=True)
            await asyncio.sleep(0.2)  # enough for 2+ keepalive ticks
            assert call_count >= 2
        finally:
            matrix_mod._TYPING_KEEPALIVE_S = original
            await ch.send_typing("matrix:@alice:example.org", typing=False)

    @pytest.mark.asyncio
    async def test_typing_429_retries_after_delay(self) -> None:
        """Keepalive loop sleeps for retry_after_ms on 429 and retries."""
        from squidbot.adapters.channels import matrix as matrix_mod
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)
        call_count = 0

        rate_limit_resp = MagicMock(spec=["retry_after_ms"])
        rate_limit_resp.retry_after_ms = 50  # 50ms retry

        ok_resp = MagicMock()
        # First call returns rate-limited, subsequent calls succeed
        responses: list[Any] = [rate_limit_resp, ok_resp, ok_resp, ok_resp]

        async def fake_room_typing(room_id: str, typing_state: bool, timeout: int = 0) -> Any:
            nonlocal call_count
            if typing_state:
                call_count += 1
                if responses:
                    return responses.pop(0)
            return MagicMock()

        ch._client = MagicMock()
        ch._client.room_typing = fake_room_typing
        ch._session_rooms["matrix:@alice:example.org"] = "!room1:example.org"

        original = matrix_mod._TYPING_KEEPALIVE_S
        matrix_mod._TYPING_KEEPALIVE_S = 0.01

        try:
            await ch.send_typing("matrix:@alice:example.org", typing=True)
            await asyncio.sleep(0.3)
            # Should have retried after the rate limit
            assert call_count >= 2
        finally:
            matrix_mod._TYPING_KEEPALIVE_S = original
            await ch.send_typing("matrix:@alice:example.org", typing=False)


class TestMatrixChannelSend:
    """MatrixChannel.send() posts correct Matrix events."""

    @pytest.mark.asyncio
    async def test_send_text_posts_formatted_message(self) -> None:
        """send() calls room_send with m.text + HTML formatted_body."""
        from squidbot.adapters.channels.matrix import MatrixChannel
        from squidbot.core.models import OutboundMessage, Session

        config = _make_config()
        ch = MatrixChannel(config=config)
        sent: list[dict[str, Any]] = []

        async def fake_room_send(
            room_id: str, message_type: str, content: dict[str, Any]
        ) -> MagicMock:
            sent.append({"room_id": room_id, "type": message_type, "content": content})
            return MagicMock()

        ch._client = MagicMock()
        ch._client.room_send = fake_room_send

        session = Session(channel="matrix", sender_id="@alice:example.org")
        msg = OutboundMessage(
            session=session,
            text="**hello**",
            metadata={"matrix_room_id": "!room1:example.org"},
        )
        await ch.send(msg)

        assert len(sent) == 1
        assert sent[0]["type"] == "m.room.message"
        assert sent[0]["content"]["msgtype"] == "m.text"
        assert sent[0]["content"]["body"] == "**hello**"
        assert "<strong>hello</strong>" in sent[0]["content"]["formatted_body"]

    @pytest.mark.asyncio
    async def test_send_text_with_thread_root_adds_relates_to(self) -> None:
        """send() with matrix_thread_root adds m.relates_to to the event."""
        from squidbot.adapters.channels.matrix import MatrixChannel
        from squidbot.core.models import OutboundMessage, Session

        config = _make_config()
        ch = MatrixChannel(config=config)
        sent: list[dict[str, Any]] = []

        async def fake_room_send(
            room_id: str, message_type: str, content: dict[str, Any]
        ) -> MagicMock:
            sent.append(content)
            return MagicMock()

        ch._client = MagicMock()
        ch._client.room_send = fake_room_send

        session = Session(channel="matrix", sender_id="@alice:example.org")
        msg = OutboundMessage(
            session=session,
            text="reply",
            metadata={
                "matrix_room_id": "!room1:example.org",
                "matrix_thread_root": "$thread_root_456",
            },
        )
        await ch.send(msg)

        assert sent[0]["m.relates_to"]["rel_type"] == "m.thread"
        assert sent[0]["m.relates_to"]["event_id"] == "$thread_root_456"
        assert sent[0]["m.relates_to"]["is_falling_back"] is True

    @pytest.mark.asyncio
    async def test_send_without_room_id_logs_and_drops(self) -> None:
        """send() with no matrix_room_id in metadata drops the message."""
        from squidbot.adapters.channels.matrix import MatrixChannel
        from squidbot.core.models import OutboundMessage, Session

        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        ch._client.room_send = AsyncMock()

        session = Session(channel="matrix", sender_id="@alice:example.org")
        msg = OutboundMessage(session=session, text="hello", metadata={})
        await ch.send(msg)

        ch._client.room_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_attachment_uploads_and_sends_media_event(self, tmp_path: Path) -> None:
        """send() with attachment uploads the file and sends a media event."""
        from squidbot.adapters.channels.matrix import MatrixChannel
        from squidbot.core.models import OutboundMessage, Session

        # Create a minimal valid JPEG (enough for magic to detect)
        jpg = tmp_path / "test.jpg"
        jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 10 + b"\xff\xd9")  # minimal JPEG

        config = _make_config()
        ch = MatrixChannel(config=config)
        sent: list[dict[str, Any]] = []

        async def fake_upload(
            data_provider: Any, content_type: str, filename: str, filesize: int
        ) -> tuple[MagicMock, Any]:
            resp = MagicMock()
            resp.content_uri = "mxc://example.org/TestMediaId"
            return resp, None

        async def fake_room_send(
            room_id: str, message_type: str, content: dict[str, Any]
        ) -> MagicMock:
            sent.append(content)
            return MagicMock()

        ch._client = MagicMock()
        ch._client.upload = fake_upload
        ch._client.room_send = fake_room_send

        session = Session(channel="matrix", sender_id="@alice:example.org")
        msg = OutboundMessage(
            session=session,
            text="",
            attachment=jpg,
            metadata={"matrix_room_id": "!room1:example.org"},
        )

        with patch("magic.from_file", return_value="image/jpeg"):
            await ch.send(msg)

        # Should have sent one media event
        media_events = [e for e in sent if e.get("msgtype") == "m.image"]
        assert len(media_events) == 1
        assert media_events[0]["url"] == "mxc://example.org/TestMediaId"
        assert media_events[0]["filename"] == "test.jpg"
