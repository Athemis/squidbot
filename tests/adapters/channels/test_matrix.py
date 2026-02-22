"""Tests for MatrixChannel — receiving messages."""

from __future__ import annotations

import asyncio
from datetime import datetime
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
