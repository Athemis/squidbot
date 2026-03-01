"""Tests for MatrixChannel — receiving messages."""

from __future__ import annotations

import asyncio
import json
import stat
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import nio
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

        with patch("squidbot.adapters.channels.matrix._detect_mime", return_value="image/jpeg"):
            await ch.send(msg)

        # Should have sent one media event
        media_events = [e for e in sent if e.get("msgtype") == "m.image"]
        assert len(media_events) == 1
        assert media_events[0]["url"] == "mxc://example.org/TestMediaId"
        assert media_events[0]["filename"] == "test.jpg"


class TestMatrixMediaMetadata:
    @pytest.mark.asyncio
    async def test_media_metadata_uses_async_ffprobe(self, tmp_path: Path) -> None:
        from squidbot.adapters.channels import matrix as matrix_mod

        media_file = tmp_path / "clip.mp4"
        media_file.write_bytes(b"video-bytes")

        ffprobe_json = {
            "format": {"duration": "1.25"},
            "streams": [{"codec_type": "video", "width": 640, "height": 360}],
        }

        class FakeProcess:
            async def communicate(self) -> tuple[bytes, bytes]:
                return json.dumps(ffprobe_json).encode("utf-8"), b""

            def kill(self) -> None:
                return

        create_proc = AsyncMock(return_value=FakeProcess())
        with patch(
            "squidbot.adapters.channels.matrix.asyncio.create_subprocess_exec",
            create_proc,
        ):
            info = await matrix_mod._media_metadata(media_file, "video/mp4")

        create_proc.assert_awaited_once()
        assert info["mimetype"] == "video/mp4"
        assert info["duration"] == 1250
        assert info["w"] == 640
        assert info["h"] == 360

    @pytest.mark.asyncio
    async def test_media_metadata_ffprobe_failure_returns_base_info(self, tmp_path: Path) -> None:
        from squidbot.adapters.channels import matrix as matrix_mod

        media_file = tmp_path / "clip.mp4"
        media_file.write_bytes(b"video-bytes")

        with patch(
            "squidbot.adapters.channels.matrix.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=FileNotFoundError),
        ):
            info = await matrix_mod._media_metadata(media_file, "video/mp4")

        assert info == {"mimetype": "video/mp4", "size": media_file.stat().st_size}

    def test_matrix_module_has_no_subprocess_run_calls(self) -> None:
        from squidbot.adapters.channels import matrix as matrix_mod

        source = Path(matrix_mod.__file__).read_text(encoding="utf-8")
        assert "subprocess.run(" not in source


class TestMatrixRoomMembershipLogging:
    """Room-membership observability logs cover joined and missing rooms."""

    def test_logs_joined_and_missing_configured_rooms(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(room_ids=["!room1:example.org", "!room2:example.org"])
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        ch._client.rooms = {
            "!room1:example.org": MagicMock(),
            "!other:example.org": MagicMock(),
        }

        with (
            patch("squidbot.adapters.channels.matrix.logger.info") as info_log,
            patch("squidbot.adapters.channels.matrix.logger.warning") as warn_log,
        ):
            ch._log_room_membership_snapshot()

        info_log.assert_called_once_with("MatrixChannel: currently joined {} room(s)", 2)
        warn_log.assert_called_once_with(
            "MatrixChannel: not joined to configured room(s): {}",
            "!room2:example.org",
        )

    def test_logs_all_configured_rooms_joined(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(room_ids=["!room1:example.org"])
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        ch._client.rooms = {"!room1:example.org": MagicMock()}

        with patch("squidbot.adapters.channels.matrix.logger.warning") as warn_log:
            ch._log_room_membership_snapshot()

        warn_log.assert_not_called()


class TestMatrixChannelE2ee:
    """MatrixChannel E2EE initialization and encrypted-event diagnostics."""

    async def test_connect_enables_e2ee_with_persistent_store_path(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config)
        fake_client = MagicMock()
        fake_client.add_event_callback = MagicMock()
        fake_cfg = MagicMock()
        fake_cfg.encryption_enabled = True
        fake_cfg.store_sync_tokens = True

        with (
            patch("squidbot.adapters.channels.matrix.nio.AsyncClientConfig", return_value=fake_cfg),
            patch(
                "squidbot.adapters.channels.matrix.nio.AsyncClient", return_value=fake_client
            ) as ctor,
        ):
            await ch._connect()

        kwargs = ctor.call_args.kwargs
        assert "/.squidbot/crypto/matrix/" in kwargs["store_path"]
        assert kwargs["config"].encryption_enabled is True
        assert kwargs["config"].store_sync_tokens is True

    async def test_connect_degrades_when_crypto_store_permissions_fail(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config)
        fake_client = MagicMock()
        fake_client.add_event_callback = MagicMock()

        with (
            patch.object(ch, "_crypto_store_path", return_value=("/tmp/store", False)),
            patch(
                "squidbot.adapters.channels.matrix.nio.AsyncClient", return_value=fake_client
            ) as ctor,
        ):
            await ch._connect()

        kwargs = ctor.call_args.kwargs
        assert "store_path" not in kwargs
        assert ch._e2ee_available is False
        assert ch._e2ee_degraded_reason == "CryptoStorePermissions"

    async def test_connect_does_not_swallow_unexpected_e2ee_errors(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config)
        fake_cfg = MagicMock()

        with (
            patch.object(ch, "_crypto_store_path", return_value=("/tmp/store", True)),
            patch("squidbot.adapters.channels.matrix.nio.AsyncClientConfig", return_value=fake_cfg),
            patch(
                "squidbot.adapters.channels.matrix.nio.AsyncClient",
                side_effect=TypeError("boom"),
            ),
            pytest.raises(TypeError, match="boom"),
        ):
            await ch._connect()

    async def test_logs_encrypted_unknown_event_details(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)

        room = MagicMock()
        room.room_id = "!room1:example.org"
        event = MagicMock()
        event.sender = "@alice:example.org"
        event.event_id = "$enc1"
        event.source = {
            "type": "m.room.encrypted",
            "content": {
                "algorithm": "m.megolm.v1.aes-sha2",
            },
        }

        with patch("squidbot.adapters.channels.matrix.logger.warning") as warn_log:
            await ch._handle_reaction(room, event)

        warn_log.assert_any_call(
            "MatrixChannel: encrypted event received room={} sender={} event={} algorithm={}",
            "!room1:example.org",
            "@alice:example.org",
            "$enc1",
            "m.megolm.v1.aes-sha2",
        )

    async def test_logs_error_for_encrypted_event_when_degraded(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._e2ee_available = False

        room = MagicMock()
        room.room_id = "!room1:example.org"
        event = MagicMock()
        event.sender = "@alice:example.org"
        event.event_id = "$enc2"
        event.source = {
            "type": "m.room.encrypted",
            "content": {"algorithm": "m.megolm.v1.aes-sha2"},
        }

        with patch("squidbot.adapters.channels.matrix.logger.error") as error_log:
            await ch._handle_reaction(room, event)

        error_log.assert_any_call(
            "MatrixChannel: encrypted event while E2EE degraded room={} sender={} event={}",
            "!room1:example.org",
            "@alice:example.org",
            "$enc2",
        )

    async def test_sync_loop_logs_enabled_readiness(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._e2ee_available = True

        client = MagicMock()
        client.rooms = {"!room1:example.org": MagicMock()}
        client.sync = AsyncMock(return_value=MagicMock())
        client.sync_forever = AsyncMock(side_effect=RuntimeError("stop"))
        ch._client = client

        with patch("squidbot.adapters.channels.matrix.logger.info") as info_log:
            await ch._sync_loop()

        info_log.assert_any_call(
            "MatrixChannel: E2EE readiness={} joined_rooms={}",
            "enabled",
            1,
        )

    async def test_sync_loop_logs_degraded_readiness_reason(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._e2ee_available = False
        ch._e2ee_degraded_reason = "ImportWarning"

        client = MagicMock()
        client.rooms = {"!room1:example.org": MagicMock()}
        client.sync = AsyncMock(return_value=MagicMock())
        client.sync_forever = AsyncMock(side_effect=RuntimeError("stop"))
        ch._client = client

        with patch("squidbot.adapters.channels.matrix.logger.warning") as warn_log:
            await ch._sync_loop()

        warn_log.assert_any_call(
            "MatrixChannel: E2EE readiness={} joined_rooms={} reason={}",
            "degraded",
            1,
            "ImportWarning",
        )

    async def test_sync_loop_logs_readiness_when_initial_sync_errors(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._e2ee_available = False
        ch._e2ee_degraded_reason = "ImportWarning"

        client = MagicMock()
        client.sync = AsyncMock(return_value=nio.SyncError("sync failed"))
        client.sync_forever = AsyncMock(side_effect=RuntimeError("stop"))
        ch._client = client

        with patch("squidbot.adapters.channels.matrix.logger.warning") as warn_log:
            await ch._sync_loop()

        warn_log.assert_any_call(
            "MatrixChannel: E2EE readiness={} joined_rooms={} reason={}",
            "degraded",
            0,
            "ImportWarning",
        )

    def test_crypto_store_path_applies_owner_only_permissions(self, tmp_path: Path) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config)

        with patch("squidbot.adapters.channels.matrix.Path.home", return_value=tmp_path):
            store_path_raw, hardened = ch._crypto_store_path("@bot:example.org")

        store_path = Path(store_path_raw)
        assert hardened is True

        mode = stat.S_IMODE(store_path.stat().st_mode)
        assert mode == 0o700


class TestMatrixChannelInvites:
    """Owner-only invite auto-join behavior."""

    async def test_invite_from_owner_triggers_join(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config, owner_matrix_ids={"@owner:example.org"})
        ch._client = MagicMock()
        ch._client.join = AsyncMock(return_value=MagicMock())

        room = MagicMock()
        room.room_id = "!dm:example.org"
        event = MagicMock()
        event.membership = "invite"
        event.state_key = "@bot:example.org"
        event.sender = "@owner:example.org"

        await ch._handle_invite(room, event)

        ch._client.join.assert_awaited_once_with("!dm:example.org")

    async def test_invite_from_non_owner_is_ignored(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config, owner_matrix_ids={"@owner:example.org"})
        ch._client = MagicMock()
        ch._client.join = AsyncMock(return_value=MagicMock())

        room = MagicMock()
        room.room_id = "!group:example.org"
        event = MagicMock()
        event.membership = "invite"
        event.state_key = "@bot:example.org"
        event.sender = "@someone:example.org"

        await ch._handle_invite(room, event)

        ch._client.join.assert_not_awaited()

    def test_owner_matrix_ids_are_copied_defensively(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        provided = {"@owner:example.org"}
        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config, owner_matrix_ids=provided)

        provided.clear()

        assert "@owner:example.org" in ch._owner_matrix_ids

    async def test_invite_with_non_matching_state_key_is_ignored(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config, owner_matrix_ids={"@owner:example.org"})
        ch._client = MagicMock()
        ch._client.join = AsyncMock(return_value=MagicMock())

        room = MagicMock()
        room.room_id = "!group:example.org"
        event = MagicMock()
        event.membership = "invite"
        event.state_key = "@other-bot:example.org"
        event.sender = "@owner:example.org"

        await ch._handle_invite(room, event)

        ch._client.join.assert_not_awaited()

    async def test_invite_join_error_is_logged(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config, owner_matrix_ids={"@owner:example.org"})

        room = MagicMock()
        room.room_id = "!group:example.org"
        event = MagicMock()
        event.membership = "invite"
        event.state_key = "@bot:example.org"
        event.sender = "@owner:example.org"

        join_error = MagicMock(spec=nio.JoinError)
        ch._client = MagicMock()
        ch._client.join = AsyncMock(return_value=join_error)

        with patch("squidbot.adapters.channels.matrix.logger.error") as error_log:
            await ch._handle_invite(room, event)

        error_log.assert_any_call(
            "MatrixChannel: auto-join failed room={} inviter={} err={}",
            "!group:example.org",
            "@owner:example.org",
            join_error,
        )

    async def test_invite_join_exception_is_logged(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config, owner_matrix_ids={"@owner:example.org"})

        room = MagicMock()
        room.room_id = "!group:example.org"
        event = MagicMock()
        event.membership = "invite"
        event.state_key = "@bot:example.org"
        event.sender = "@owner:example.org"

        boom = RuntimeError("boom")
        ch._client = MagicMock()
        ch._client.join = AsyncMock(side_effect=boom)

        with patch("squidbot.adapters.channels.matrix.logger.error") as error_log:
            await ch._handle_invite(room, event)

        error_log.assert_any_call(
            "MatrixChannel: auto-join exception room={} inviter={} err={}",
            "!group:example.org",
            "@owner:example.org",
            boom,
        )
