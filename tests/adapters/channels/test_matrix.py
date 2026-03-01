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
            room_id: str,
            message_type: str,
            content: dict[str, Any],
            ignore_unverified_devices: bool = False,
        ) -> MagicMock:
            sent.append(
                {
                    "room_id": room_id,
                    "type": message_type,
                    "content": content,
                    "ignore_unverified_devices": ignore_unverified_devices,
                }
            )
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
        assert sent[0]["ignore_unverified_devices"] is True

    @pytest.mark.asyncio
    async def test_send_text_with_thread_root_adds_relates_to(self) -> None:
        """send() with matrix_thread_root adds m.relates_to to the event."""
        from squidbot.adapters.channels.matrix import MatrixChannel
        from squidbot.core.models import OutboundMessage, Session

        config = _make_config()
        ch = MatrixChannel(config=config)
        sent: list[dict[str, Any]] = []

        async def fake_room_send(
            room_id: str,
            message_type: str,
            content: dict[str, Any],
            ignore_unverified_devices: bool = False,
        ) -> MagicMock:
            sent.append(
                {"content": content, "ignore_unverified_devices": ignore_unverified_devices}
            )
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

        assert sent[0]["content"]["m.relates_to"]["rel_type"] == "m.thread"
        assert sent[0]["content"]["m.relates_to"]["event_id"] == "$thread_root_456"
        assert sent[0]["content"]["m.relates_to"]["is_falling_back"] is True
        assert sent[0]["ignore_unverified_devices"] is True

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
        """send() with attachments uploads the file and sends a media event."""
        import io

        from squidbot.adapters.channels.matrix import MatrixChannel
        from squidbot.core.models import OutboundMessage, Session

        # Create a minimal valid JPEG (enough for magic to detect)
        jpg = tmp_path / "test.jpg"
        jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 10 + b"\xff\xd9")  # minimal JPEG

        config = _make_config()
        ch = MatrixChannel(config=config)
        sent: list[dict[str, Any]] = []
        upload_args: list[Any] = []

        async def fake_upload(
            data: Any, content_type: str, filename: str, filesize: int
        ) -> tuple[MagicMock, Any]:
            upload_args.append(data)
            resp = MagicMock()
            resp.content_uri = "mxc://example.org/TestMediaId"
            return resp, None

        async def fake_room_send(
            room_id: str,
            message_type: str,
            content: dict[str, Any],
            ignore_unverified_devices: bool = False,
        ) -> MagicMock:
            sent.append(
                {"content": content, "ignore_unverified_devices": ignore_unverified_devices}
            )
            return MagicMock()

        ch._client = MagicMock()
        ch._client.upload = fake_upload
        ch._client.room_send = fake_room_send
        ch._client.content_repository_config = AsyncMock(return_value=MagicMock(upload_size=None))

        session = Session(channel="matrix", sender_id="@alice:example.org")
        msg = OutboundMessage(
            session=session,
            text="done",
            attachments=[jpg],
            metadata={"matrix_room_id": "!room1:example.org"},
        )

        with patch("squidbot.adapters.channels.matrix._detect_mime", return_value="image/jpeg"):
            await ch.send(msg)

        # Upload must receive io.BytesIO, not a lambda
        assert len(upload_args) == 1
        assert isinstance(upload_args[0], io.BytesIO), (
            f"Expected BytesIO but got {type(upload_args[0])}"
        )

        # Should have sent media before text
        assert len(sent) == 2
        assert sent[0]["content"]["msgtype"] == "m.image"
        assert sent[1]["content"]["msgtype"] == "m.text"

        media_events = [e for e in sent if e["content"].get("msgtype") == "m.image"]
        assert len(media_events) == 1
        assert media_events[0]["content"]["url"] == "mxc://example.org/TestMediaId"
        assert media_events[0]["content"]["filename"] == "test.jpg"
        assert media_events[0]["ignore_unverified_devices"] is True

        text_events = [e for e in sent if e["content"].get("msgtype") == "m.text"]
        assert len(text_events) == 1
        assert sent.index(media_events[0]) < sent.index(text_events[0])

    @pytest.mark.asyncio
    async def test_send_multiple_attachments_uploads_each(self, tmp_path: Path) -> None:
        """send() with multiple attachments uploads and sends each as a separate media event."""
        import io

        from squidbot.adapters.channels.matrix import MatrixChannel
        from squidbot.core.models import OutboundMessage, Session

        jpg1 = tmp_path / "photo1.jpg"
        jpg1.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 10 + b"\xff\xd9")
        jpg2 = tmp_path / "photo2.jpg"
        jpg2.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20 + b"\xff\xd9")

        config = _make_config()
        ch = MatrixChannel(config=config)
        upload_calls: list[Any] = []
        sent: list[dict[str, Any]] = []
        media_id = 0

        async def fake_upload(data: Any, content_type: str, filename: str, filesize: int) -> Any:
            nonlocal media_id
            upload_calls.append(data)
            media_id += 1
            resp = MagicMock()
            resp.content_uri = f"mxc://example.org/Media{media_id}"
            return resp, None

        async def fake_room_send(
            room_id: str,
            message_type: str,
            content: dict[str, Any],
            ignore_unverified_devices: bool = False,
        ) -> MagicMock:
            sent.append({"content": content})
            return MagicMock()

        ch._client = MagicMock()
        ch._client.upload = fake_upload
        ch._client.room_send = fake_room_send
        ch._client.content_repository_config = AsyncMock(return_value=MagicMock(upload_size=None))

        session = Session(channel="matrix", sender_id="@alice:example.org")
        msg = OutboundMessage(
            session=session,
            text="",
            attachments=[jpg1, jpg2],
            metadata={"matrix_room_id": "!room1:example.org"},
        )

        with patch("squidbot.adapters.channels.matrix._detect_mime", return_value="image/jpeg"):
            await ch.send(msg)

        assert len(upload_calls) == 2
        assert all(isinstance(a, io.BytesIO) for a in upload_calls)
        media_events = [e for e in sent if e["content"].get("msgtype") == "m.image"]
        assert len(media_events) == 2

    @pytest.mark.asyncio
    async def test_send_skips_attachment_exceeding_effective_outbound_limit(
        self, tmp_path: Path
    ) -> None:
        """Attachment larger than effective outbound limit is skipped."""
        from squidbot.adapters.channels.matrix import MatrixChannel
        from squidbot.core.models import OutboundMessage, Session

        big_file = tmp_path / "big.bin"
        big_file.write_bytes(b"x" * 100)  # small content, but we'll fake a tiny limit

        config = _make_config(max_outbound_upload_bytes=50)  # only 50 bytes allowed
        ch = MatrixChannel(config=config)
        upload_called = False

        async def fake_upload(data: Any, content_type: str, filename: str, filesize: int) -> Any:
            nonlocal upload_called
            upload_called = True
            return MagicMock(), None

        ch._client = MagicMock()
        ch._client.upload = fake_upload
        ch._client.room_send = AsyncMock(return_value=MagicMock())
        ch._client.content_repository_config = AsyncMock(return_value=MagicMock(upload_size=None))

        session = Session(channel="matrix", sender_id="@alice:example.org")
        msg = OutboundMessage(
            session=session,
            text="",
            attachments=[big_file],
            metadata={"matrix_room_id": "!room1:example.org"},
        )

        await ch.send(msg)

        assert not upload_called, "Upload should have been skipped"

    @pytest.mark.asyncio
    async def test_send_uses_min_of_local_and_server_upload_limit(self, tmp_path: Path) -> None:
        """Effective outbound limit uses min(local, server) when server limit is available."""
        from squidbot.adapters.channels.matrix import MatrixChannel
        from squidbot.core.models import OutboundMessage, Session

        big_file = tmp_path / "medium.bin"
        big_file.write_bytes(b"x" * 200)

        # Local limit is 1000 bytes but server allows only 100 bytes
        config = _make_config(max_outbound_upload_bytes=1000)
        ch = MatrixChannel(config=config)
        upload_called = False

        async def fake_upload(data: Any, content_type: str, filename: str, filesize: int) -> Any:
            nonlocal upload_called
            upload_called = True
            return MagicMock(), None

        server_cfg = MagicMock()
        server_cfg.upload_size = 100  # server limit is 100 bytes

        ch._client = MagicMock()
        ch._client.upload = fake_upload
        ch._client.room_send = AsyncMock(return_value=MagicMock())
        ch._client.content_repository_config = AsyncMock(return_value=server_cfg)

        session = Session(channel="matrix", sender_id="@alice:example.org")
        msg = OutboundMessage(
            session=session,
            text="",
            attachments=[big_file],
            metadata={"matrix_room_id": "!room1:example.org"},
        )

        await ch.send(msg)

        assert not upload_called, "File exceeds server limit, upload should be skipped"


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

        info_log.assert_not_called()
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

    async def test_connect_logs_install_hint_when_e2ee_support_missing(self) -> None:
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config)
        fake_client = MagicMock()
        fake_client.add_event_callback = MagicMock()

        with (
            patch.object(ch, "_crypto_store_path", return_value=("/tmp/store", True)),
            patch(
                "squidbot.adapters.channels.matrix.nio.AsyncClientConfig",
                side_effect=ImportError("missing e2e extras"),
            ),
            patch("squidbot.adapters.channels.matrix.nio.AsyncClient", return_value=fake_client),
            patch("squidbot.adapters.channels.matrix.logger.warning") as warn_log,
        ):
            await ch._connect()

        warn_log.assert_any_call(
            "MatrixChannel: E2EE unavailable ({}). "
            "Install matrix-nio[e2e] to enable encrypted DMs.",
            "ImportError",
        )

    async def test_connect_degrades_when_load_store_fails(self) -> None:
        """_connect() sets _e2ee_available=False and records reason when load_store() raises."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config)
        fake_cfg = MagicMock()
        fake_client = MagicMock()
        fake_client.add_event_callback = MagicMock()
        fake_client.load_store = MagicMock(side_effect=RuntimeError("db locked"))

        with (
            patch.object(ch, "_crypto_store_path", return_value=("/tmp/store", True)),
            patch("squidbot.adapters.channels.matrix.nio.AsyncClientConfig", return_value=fake_cfg),
            patch("squidbot.adapters.channels.matrix.nio.AsyncClient", return_value=fake_client),
        ):
            await ch._connect()

        assert ch._e2ee_available is False
        assert ch._e2ee_degraded_reason == "StoreLoad:RuntimeError"

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

        info_log.assert_any_call("MatrixChannel: E2EE readiness=enabled")

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
            "MatrixChannel: E2EE readiness=degraded reason={}",
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
            "MatrixChannel: E2EE readiness=degraded reason={}",
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


class TestMatrixInboundGuardrails:
    """Inbound attachment download, embedding, and guardrail tests."""

    def _make_media_event(
        self,
        mxc: str = "mxc://example.org/abc123",
        filename: str = "photo.jpg",
        mime: str = "image/jpeg",
        declared_size: int | None = None,
    ) -> MagicMock:
        """Build a minimal media event mock."""
        event = MagicMock()
        event.sender = "@alice:example.org"
        event.room_id = "!room1:example.org"
        event.event_id = "$media1"
        event.url = mxc
        event.file = None  # not encrypted
        event.body = filename
        event.source = {"content": {}}
        event.server_timestamp = int(datetime.now().timestamp() * 1000)
        info = MagicMock()
        info.mimetype = mime
        if declared_size is not None:
            info.size = declared_size
        else:
            del info.size  # Absent attribute raises AttributeError
        event.info = info
        return event

    def _make_download_resp(self, body: bytes, mime: str) -> MagicMock:
        resp = MagicMock()
        resp.body = body
        resp.content_type = mime
        return resp

    async def test_jpeg_under_embed_limit_produces_multimodal_content(self, tmp_path: Path) -> None:
        """JPEG under embed limit embeds as Base64 image_url block."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)
        image_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # ~100 bytes, well under 2MB

        ch._client = MagicMock()
        ch._client.download = AsyncMock(
            return_value=self._make_download_resp(image_bytes, "image/jpeg")
        )

        event = self._make_media_event(mime="image/jpeg")
        event.info.mimetype = "image/jpeg"

        text, multimodal = await ch._download_attachment(event)

        assert multimodal is not None, "Expected multimodal content for JPEG under embed limit"
        assert any(b.get("type") == "image_url" for b in multimodal), (
            "Expected image_url block in multimodal content"
        )
        assert any(b.get("type") == "text" for b in multimodal), "Expected text block"

    async def test_svg_produces_no_multimodal_content(self, tmp_path: Path) -> None:
        """SVG (non-allowlist MIME) does not embed — text path only."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)
        svg_bytes = b"<svg><circle r='10'/></svg>"

        ch._client = MagicMock()
        ch._client.download = AsyncMock(
            return_value=self._make_download_resp(svg_bytes, "image/svg+xml")
        )

        event = self._make_media_event(mime="image/svg+xml", filename="icon.svg")
        event.info.mimetype = "image/svg+xml"

        text, multimodal = await ch._download_attachment(event)

        assert multimodal is None, "SVG must not be embedded"
        assert "icon.svg" in text

    async def test_declared_size_above_download_limit_skips_download(self) -> None:
        """If declared size exceeds max_inbound_download_bytes, skip download."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        limit = 50 * 1024 * 1024
        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        download_mock = AsyncMock()
        ch._client.download = download_mock

        event = self._make_media_event(
            declared_size=limit + 1, mime="image/jpeg", filename="huge.jpg"
        )

        text, multimodal = await ch._download_attachment(event)

        download_mock.assert_not_awaited()
        assert multimodal is None
        assert "zu groß" in text or "huge.jpg" in text

    async def test_downloaded_size_above_embed_limit_produces_no_embedding(self) -> None:
        """Downloaded content > max_inbound_embed_bytes: text path only, no embedding."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        # 1.6MB raw bytes → encoded > 2.1MB → exceeds 2MB embed limit
        image_bytes = b"\xff\xd8" + b"\x00" * (1_600_000)

        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        ch._client.download = AsyncMock(
            return_value=self._make_download_resp(image_bytes, "image/jpeg")
        )

        event = self._make_media_event(mime="image/jpeg")
        event.info.mimetype = "image/jpeg"

        text, multimodal = await ch._download_attachment(event)

        assert multimodal is None, "Oversized image should not be embedded"

    async def test_downloaded_size_above_download_limit_post_fetch_fallback(self) -> None:
        """Downloaded content > max_inbound_download_bytes triggers post-fetch fallback."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        download_limit = 50 * 1024 * 1024  # 50 MB
        image_bytes = b"\x00" * (download_limit + 100)

        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        ch._client.download = AsyncMock(
            return_value=self._make_download_resp(image_bytes, "image/jpeg")
        )

        event = self._make_media_event(mime="image/jpeg", filename="toobig.jpg")
        event.info.mimetype = "image/jpeg"

        text, multimodal = await ch._download_attachment(event)

        assert multimodal is None
        assert "zu groß" in text

    async def test_non_allowlist_file_downloaded_and_text_path_returned(
        self, tmp_path: Path
    ) -> None:
        """Non-allowlist file (PDF) is still downloaded, persisted, text path returned."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)
        pdf_bytes = b"%PDF-1.4 content here"

        ch._client = MagicMock()
        ch._client.download = AsyncMock(
            return_value=self._make_download_resp(pdf_bytes, "application/pdf")
        )

        event = self._make_media_event(mime="application/pdf", filename="doc.pdf")
        event.info.mimetype = "application/pdf"

        text, multimodal = await ch._download_attachment(event)

        assert multimodal is None, "PDF must not be embedded"
        assert "doc.pdf" in text
        # Text should contain a path to the saved file
        assert "/tmp" in text or "squidbot" in text.lower()

    async def test_multimodal_propagated_from_download_to_inbound_message(self) -> None:
        """_handle_media propagates multimodal_content exactly as returned by
        _download_attachment."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="open")
        ch = MatrixChannel(config=config)
        image_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100

        ch._client = MagicMock()
        ch._client.download = AsyncMock(
            return_value=self._make_download_resp(image_bytes, "image/jpeg")
        )

        event = self._make_media_event(mime="image/jpeg", filename="photo.jpg")
        event.info.mimetype = "image/jpeg"

        await ch._handle_media(MagicMock(), event)

        assert not ch._queue.empty()
        msg = ch._queue.get_nowait()
        assert msg.multimodal_content is not None
        assert any(b.get("type") == "image_url" for b in msg.multimodal_content)

    async def test_encoded_size_boundary_just_below_embeds(self) -> None:
        """Image whose encoded size is exactly at embed limit is embedded."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        # Find raw size such that estimated_encoded_bytes == max_inbound_embed_bytes
        # Formula: 4 * ((raw + 2) // 3) + len("data:image/jpeg;base64,") = 2097152
        header = len("data:image/jpeg;base64,")
        target_encoded = 2 * 1024 * 1024  # exactly at embed limit
        # work backward: encoded_data_part = target_encoded - header
        encoded_data_part = target_encoded - header
        # 4 * ((raw + 2) // 3) = encoded_data_part → raw ≈ encoded_data_part * 3 / 4
        raw_bytes_count = (encoded_data_part * 3) // 4 - 2

        image_bytes = b"\xff\xd8" + b"\x00" * max(0, raw_bytes_count - 2)

        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        ch._client.download = AsyncMock(
            return_value=self._make_download_resp(image_bytes, "image/jpeg")
        )

        event = self._make_media_event(mime="image/jpeg")
        event.info.mimetype = "image/jpeg"

        text, multimodal = await ch._download_attachment(event)

        # A file right at or below the boundary should embed.
        # Assert precondition first so the test fails if fixture math drifts.
        estimated = 4 * ((len(image_bytes) + 2) // 3) + header
        assert estimated <= target_encoded, (
            f"Fixture miscomputed boundary: estimated={estimated}, target={target_encoded}"
        )
        assert multimodal is not None

    async def test_fallback_reason_non_image_logged(self) -> None:
        """non-image MIME emits debug log with reason=non-image."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        ch._client.download = AsyncMock(
            return_value=self._make_download_resp(b"<svg/>", "image/svg+xml")
        )

        event = self._make_media_event(mime="image/svg+xml", filename="icon.svg")
        event.info.mimetype = "image/svg+xml"

        with patch("squidbot.adapters.channels.matrix.logger.debug") as dbg:
            await ch._download_attachment(event)

        debug_calls = [str(c) for c in dbg.call_args_list]
        assert any("non-image" in c for c in debug_calls), (
            f"Expected 'non-image' in debug calls, got: {debug_calls}"
        )

    async def test_fallback_reason_exceeds_embed_limit_logged(self) -> None:
        """Oversized image emits debug log with reason=exceeds_embed_limit."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        image_bytes = b"\xff\xd8" + b"\x00" * 1_600_000
        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        ch._client.download = AsyncMock(
            return_value=self._make_download_resp(image_bytes, "image/jpeg")
        )

        event = self._make_media_event(mime="image/jpeg")
        event.info.mimetype = "image/jpeg"

        with patch("squidbot.adapters.channels.matrix.logger.debug") as dbg:
            await ch._download_attachment(event)

        debug_calls = [str(c) for c in dbg.call_args_list]
        assert any("exceeds_embed_limit" in c for c in debug_calls), (
            f"Expected 'exceeds_embed_limit' in debug calls, got: {debug_calls}"
        )

    async def test_fallback_reason_exceeds_download_limit_preflight_logged(self) -> None:
        """Declared size exceeds download limit emits preflight reason."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        limit = 50 * 1024 * 1024
        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        ch._client.download = AsyncMock()

        event = self._make_media_event(declared_size=limit + 1, mime="image/jpeg")
        event.info.mimetype = "image/jpeg"

        with patch("squidbot.adapters.channels.matrix.logger.debug") as dbg:
            await ch._download_attachment(event)

        debug_calls = [str(c) for c in dbg.call_args_list]
        assert any("exceeds_download_limit_preflight" in c for c in debug_calls), (
            f"Expected 'exceeds_download_limit_preflight' in debug calls, got: {debug_calls}"
        )

    async def test_fallback_reason_exceeds_download_limit_postfetch_logged(self) -> None:
        """Downloaded content exceeds download limit emits postfetch reason."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        limit = 50 * 1024 * 1024
        image_bytes = b"\x00" * (limit + 100)
        config = _make_config()
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        ch._client.download = AsyncMock(
            return_value=self._make_download_resp(image_bytes, "image/jpeg")
        )

        event = self._make_media_event(mime="image/jpeg")
        event.info.mimetype = "image/jpeg"

        with patch("squidbot.adapters.channels.matrix.logger.debug") as dbg:
            await ch._download_attachment(event)

        debug_calls = [str(c) for c in dbg.call_args_list]
        assert any("exceeds_download_limit_postfetch" in c for c in debug_calls), (
            f"Expected 'exceeds_download_limit_postfetch' in debug calls, got: {debug_calls}"
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


class TestMatrixEncryptedMediaIntake:
    """Encrypted media intake: RoomEncryptedMedia callbacks, BadEvent routing, and decryption."""

    def _make_bad_event_with_media(
        self,
        msgtype: str = "m.file",
        filename: str = "doc.pdf",
        mxc: str = "mxc://example.com/abc",
        key_k: str = "base64key",
        iv: str = "base64iv",
        sha256: str = "base64hash",
    ) -> nio.BadEvent:
        """Build a nio.BadEvent whose content has the encrypted-file shape."""
        source: dict[str, Any] = {
            "sender": "@alice:example.org",
            "event_id": "$bad1",
            "origin_server_ts": 0,
            "room_id": "!room1:example.org",
            "type": "m.room.message",
            "unsigned": {},
            "content": {
                "msgtype": msgtype,
                "body": filename,
                "file": {
                    "url": mxc,
                    "key": {
                        "k": key_k,
                        "kty": "oct",
                        "alg": "A256CTR",
                        "key_ops": ["encrypt", "decrypt"],
                        "ext": True,
                    },
                    "iv": iv,
                    "hashes": {"sha256": sha256},
                },
            },
        }
        return nio.BadEvent(
            source=source,
            event_id="$bad1",
            sender="@alice:example.org",
            server_timestamp=0,
            type="m.room.message",
        )

    def _make_plain_media_event(
        self,
        mxc: str = "mxc://example.org/abc123",
        filename: str = "photo.jpg",
        mime: str = "image/jpeg",
        declared_size: int | None = None,
    ) -> MagicMock:
        """Build a minimal plain (non-encrypted) media event mock."""
        event = MagicMock()
        event.sender = "@alice:example.org"
        event.room_id = "!room1:example.org"
        event.event_id = "$media1"
        event.url = mxc
        event.file = None
        event.body = filename
        event.source = {"content": {}}
        event.server_timestamp = int(datetime.now().timestamp() * 1000)
        info = MagicMock()
        info.mimetype = mime
        if declared_size is not None:
            info.size = declared_size
        else:
            del info.size
        event.info = info
        return event

    # ── Callback registration ─────────────────────────────────────────────────

    async def test_registers_room_message_and_room_encrypted_media_callbacks(self) -> None:
        """_connect() registers _handle_media for both RoomMessageMedia and RoomEncryptedMedia.

        This is the pre-existing RED test (added in this branch) verifying the callback
        registration gap. The more complete version is
        test_registers_room_message_media_encrypted_media_and_bad_event_callbacks.

        The implementation uses a single tuple registration (MEDIA_EVENT_FILTER) rather than
        two individual registrations, so we flatten tuples when checking coverage.
        """
        from squidbot.adapters.channels.matrix import MatrixChannel

        def _covered_types(call_args_list: list[Any]) -> set[type]:
            """Flatten registered types from individual and tuple registrations."""
            types: set[type] = set()
            for c in call_args_list:
                filter_arg = c.args[1]
                if isinstance(filter_arg, tuple):
                    types.update(filter_arg)
                else:
                    types.add(filter_arg)
            return types

        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config)
        fake_cfg = MagicMock()
        fake_client = MagicMock()
        fake_client.add_event_callback = MagicMock()
        fake_client.load_store = MagicMock()

        with (
            patch.object(ch, "_crypto_store_path", return_value=("/tmp/store", True)),
            patch("squidbot.adapters.channels.matrix.nio.AsyncClientConfig", return_value=fake_cfg),
            patch("squidbot.adapters.channels.matrix.nio.AsyncClient", return_value=fake_client),
        ):
            await ch._connect()

        covered = _covered_types(fake_client.add_event_callback.call_args_list)

        assert nio.RoomMessageMedia in covered
        assert nio.RoomEncryptedMedia in covered

    # ── BadEvent routing ──────────────────────────────────────────────────────

    async def test_encrypted_file_with_content_file_url_is_processed(self) -> None:
        """Encrypted m.file with content.file.url is downloaded via _download_attachment.

        Verifies the BadEvent-routing path: when nio returns BadEvent for an event
        with content.file.url shape, _handle_bad_event must extract the mxc URL from
        source['content']['file']['url'] and pass it through the download pipeline.
        """
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="open")
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        download_resp = MagicMock()
        download_resp.body = b"%PDF-1.7 encrypted"
        download_resp.content_type = "application/pdf"
        ch._client.download = AsyncMock(return_value=download_resp)

        event = MagicMock()
        event.url = ""
        event.file = None
        event.body = "secret.pdf"
        event.source = {
            "content": {
                "msgtype": "m.file",
                "file": {
                    "url": "mxc://example.org/encrypted_media_123",
                },
            }
        }
        event.info = MagicMock()
        event.info.mimetype = "application/pdf"

        text, multimodal = await ch._download_attachment(event)

        ch._client.download.assert_awaited_once_with(
            server_name="example.org",
            media_id="encrypted_media_123",
        )
        assert "secret.pdf" in text
        assert multimodal is None

    async def test_media_event_not_dropped_only_due_to_filename_without_mention(self) -> None:
        """Mention policy must not drop media events because the filename lacks a bot mention.

        Media event bodies are filenames, not user text. The mention check in _accept_event
        compares event.body against config.user_id — for media events this produces false
        negatives. _handle_media (and _handle_bad_event) must bypass this check or use
        a separate acceptance path for media msgtypes.
        """
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="mention")
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        ch._download_attachment = AsyncMock(return_value=("[Anhang: invoice.pdf]", None))

        event = self._make_plain_media_event(filename="invoice.pdf", mime="application/pdf")
        event.source = {"content": {"msgtype": "m.file"}}

        await ch._handle_media(MagicMock(), event)

        assert not ch._queue.empty()
        ch._download_attachment.assert_awaited_once_with(event)

    # ── Full encrypted-media callback registration ────────────────────────────

    async def test_registers_room_message_media_encrypted_media_and_bad_event_callbacks(
        self,
    ) -> None:
        """_connect() registers _handle_media for both RoomMessageMedia and RoomEncryptedMedia,
        and _handle_bad_event for BadEvent."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(user_id="@bot:example.org")
        ch = MatrixChannel(config=config)
        fake_cfg = MagicMock()
        fake_client = MagicMock()
        fake_client.add_event_callback = MagicMock()
        fake_client.load_store = MagicMock()

        with (
            patch.object(ch, "_crypto_store_path", return_value=("/tmp/store", True)),
            patch("squidbot.adapters.channels.matrix.nio.AsyncClientConfig", return_value=fake_cfg),
            patch("squidbot.adapters.channels.matrix.nio.AsyncClient", return_value=fake_client),
        ):
            await ch._connect()

        calls = fake_client.add_event_callback.call_args_list

        # _handle_media must be registered for (RoomMessageMedia, RoomEncryptedMedia) as a tuple
        assert any(
            c.args[0] == ch._handle_media
            and isinstance(c.args[1], tuple)
            and set(c.args[1]) == {nio.RoomMessageMedia, nio.RoomEncryptedMedia}
            for c in calls
        ), (
            "_handle_media must be registered with (RoomMessageMedia, RoomEncryptedMedia) tuple. "
            f"Actual calls: {calls}"
        )

        # _handle_bad_event must be registered for BadEvent
        assert any(
            c.args[0] == ch._handle_bad_event and c.args[1] is nio.BadEvent for c in calls
        ), f"_handle_bad_event must be registered for nio.BadEvent. Actual calls: {calls}"

    async def test_bad_event_with_media_shape_routes_to_media_pipeline(self) -> None:
        """A BadEvent whose content has the encrypted-file shape is routed to the media pipeline."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="open")
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        ch._download_attachment = AsyncMock(
            return_value=("[Anhang: doc.pdf (application/pdf)] → /tmp/abc.pdf", None)
        )

        room = MagicMock()
        room.room_id = "!room1:example.org"
        event = self._make_bad_event_with_media(msgtype="m.file", filename="doc.pdf")

        await ch._handle_bad_event(room, event)

        assert not ch._queue.empty(), "Expected an InboundMessage to be queued for media BadEvent"
        msg = ch._queue.get_nowait()
        assert msg.session.sender_id == "@alice:example.org"
        # _download_attachment must be called with just the event (same as _handle_media)
        ch._download_attachment.assert_awaited_once_with(event)

    async def test_bad_event_without_media_shape_is_ignored(self) -> None:
        """A BadEvent whose content is a plain text event (no 'file' key) is ignored."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="open")
        ch = MatrixChannel(config=config)

        source: dict[str, Any] = {
            "sender": "@alice:example.org",
            "event_id": "$bad2",
            "origin_server_ts": 0,
            "room_id": "!room1:example.org",
            "type": "m.room.message",
            "unsigned": {},
            "content": {"msgtype": "m.text", "body": "hello"},
        }
        event = nio.BadEvent(
            source=source,
            event_id="$bad2",
            sender="@alice:example.org",
            server_timestamp=0,
            type="m.room.message",
        )

        room = MagicMock()
        room.room_id = "!room1:example.org"

        await ch._handle_bad_event(room, event)

        assert ch._queue.empty(), "Non-media BadEvent must not produce an InboundMessage"

    async def test_room_encrypted_media_decrypt_uses_key_k_and_hashes_sha256(self) -> None:
        """_download_attachment passes positional strings to decrypt_attachment,
        not a dict — guards against the pre-existing bug on matrix.py:773."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)

        ciphertext = b"\x00" * 32

        ch._client = MagicMock()
        ch._client.download = AsyncMock(
            return_value=MagicMock(body=ciphertext, content_type="application/pdf")
        )

        # nio.RoomEncryptedFile lacks room_id, info, and file attributes that
        # _download_attachment reads (the event IS the encrypted wrapper; the production
        # code detects E2EE via event.file, not by isinstance-checking the event type).
        # A MagicMock lets us set exactly the attributes the current production code reads.
        enc_file_event = MagicMock()
        enc_file_event.sender = "@alice:example.org"
        enc_file_event.room_id = "!room1:example.org"
        enc_file_event.event_id = "$enc1"
        enc_file_event.server_timestamp = 0
        enc_file_event.body = "encrypted.pdf"
        enc_file_event.source = {"content": {}}
        enc_file_event.url = "mxc://example.com/enc"
        enc_file_event.info = MagicMock()
        enc_file_event.info.mimetype = "application/pdf"
        # event.file triggers the E2EE decryption path in _download_attachment.
        # Its attrs (key.k, hashes["sha256"], iv) are what the fixed code should read.
        file_attr = MagicMock()
        file_attr.url = "mxc://example.com/enc"
        file_attr.key = MagicMock()
        file_attr.key.k = "base64key"
        file_attr.key.key_type = "oct"
        file_attr.key.alg = "A256CTR"
        file_attr.key.key_ops = ["encrypt", "decrypt"]
        file_attr.key.ext = True
        file_attr.iv = "base64iv"
        file_attr.hashes = {"sha256": "base64hash"}
        file_attr.v = "v2"
        enc_file_event.file = file_attr

        # Patch at source because matrix.py imports decrypt_attachment lazily inside the
        # function body: `from nio.crypto.attachments import decrypt_attachment`
        with patch("nio.crypto.attachments.decrypt_attachment") as mock_decrypt:
            mock_decrypt.return_value = b"decrypted content"
            await ch._download_attachment(enc_file_event)

        mock_decrypt.assert_called_once()
        call_args = mock_decrypt.call_args
        # Must be called with positional strings: (ciphertext, key_str, hash_str, iv_str)
        # NOT called with a dict as the second argument
        positional = call_args.args
        n = len(positional)
        assert n == 4, (
            f"Expected 4 positional args (ciphertext, key, hash, iv), got {n}: {positional}"
        )
        assert not isinstance(positional[1], dict), (
            f"decrypt_attachment arg[1] (key) must be a string, not a dict. Got: {positional[1]!r}"
        )
        assert positional[1] == "base64key", f"Expected key='base64key', got: {positional[1]!r}"
        assert positional[2] == "base64hash", f"Expected hash='base64hash', got: {positional[2]!r}"
        assert positional[3] == "base64iv", f"Expected iv='base64iv', got: {positional[3]!r}"

    async def test_bad_event_media_decrypt_uses_source_content_file_key_material(self) -> None:
        """_handle_bad_event extracts key material from source['content']['file']
        and passes positional strings to decrypt_attachment."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="open")
        ch = MatrixChannel(config=config)
        ciphertext = b"\x00" * 32

        event = self._make_bad_event_with_media(
            mxc="mxc://example.com/badsec",
            key_k="bad_base64key",
            iv="bad_base64iv",
            sha256="bad_base64hash",
        )

        room = MagicMock()
        room.room_id = "!room1:example.org"

        ch._client = MagicMock()
        ch._client.download = AsyncMock(
            return_value=MagicMock(body=ciphertext, content_type="application/pdf")
        )

        # Patch at source because matrix.py imports decrypt_attachment lazily inside the
        # function body: `from nio.crypto.attachments import decrypt_attachment`
        with patch("nio.crypto.attachments.decrypt_attachment") as mock_decrypt:
            mock_decrypt.return_value = b"decrypted pdf content"
            await ch._handle_bad_event(room, event)

        mock_decrypt.assert_called_once()
        call_args = mock_decrypt.call_args
        positional = call_args.args
        n = len(positional)
        assert n == 4, (
            f"Expected 4 positional args (ciphertext, key, hash, iv), got {n}: {positional}"
        )
        assert positional[1] == "bad_base64key", (
            f"Expected key='bad_base64key', got: {positional[1]!r}"
        )
        assert positional[2] == "bad_base64hash", (
            f"Expected hash='bad_base64hash', got: {positional[2]!r}"
        )
        assert positional[3] == "bad_base64iv", (
            f"Expected iv='bad_base64iv', got: {positional[3]!r}"
        )

    async def test_debug_logs_include_event_class_and_media_shape(self) -> None:
        """DEBUG log lines at five boundaries include required fields.

        Captures loguru output at DEBUG level and asserts that:
        - callback registration log contains 'MatrixChannel: registered callbacks classes='
        - event classification log contains 'MatrixChannel: classify event=' with
          class, msgtype, has_url, has_file_url, has_key_material fields
        - policy decision log contains 'MatrixChannel: policy event=' with result and reason
        - download/decrypt branch log contains 'MatrixChannel: download event=' with
          encrypted and url fields
        - embed decision log contains 'MatrixChannel: embed mxc=' with embedded and reason fields
        """
        import io

        from loguru import logger

        from squidbot.adapters.channels.matrix import MatrixChannel

        # Capture loguru output at DEBUG level
        output = io.StringIO()
        sink_id = logger.add(output, level="DEBUG", format="{message}")

        try:
            # --- Test classify + policy + download + embed logs via _handle_media ---
            config = _make_config(group_policy="open")
            ch = MatrixChannel(config=config)

            image_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
            download_resp = MagicMock()
            download_resp.body = image_bytes
            download_resp.content_type = "image/jpeg"

            ch._client = MagicMock()
            ch._client.download = AsyncMock(return_value=download_resp)

            event = MagicMock()
            event.sender = "@alice:example.org"
            event.room_id = "!room1:example.org"
            event.event_id = "$diag1"
            event.url = "mxc://example.org/diagmedia"
            event.file = None
            event.body = "photo.jpg"
            event.source = {"content": {}}
            event.server_timestamp = int(datetime.now().timestamp() * 1000)
            info = MagicMock()
            info.mimetype = "image/jpeg"
            del info.size
            event.info = info

            await ch._handle_media(MagicMock(), event)

            # --- Test callback registration log via _connect ---
            config2 = _make_config(user_id="@bot:example.org")
            ch2 = MatrixChannel(config=config2)
            fake_cfg = MagicMock()
            fake_client = MagicMock()
            fake_client.add_event_callback = MagicMock()
            fake_client.load_store = MagicMock()

            with (
                patch.object(ch2, "_crypto_store_path", return_value=("/tmp/store", True)),
                patch(
                    "squidbot.adapters.channels.matrix.nio.AsyncClientConfig",
                    return_value=fake_cfg,
                ),
                patch(
                    "squidbot.adapters.channels.matrix.nio.AsyncClient",
                    return_value=fake_client,
                ),
            ):
                await ch2._connect()

            log_output = output.getvalue()

            # Boundary 1: callback registration
            assert "MatrixChannel: registered callbacks classes=" in log_output, (
                f"Expected 'MatrixChannel: registered callbacks classes=' in log output.\n"
                f"Got:\n{log_output}"
            )

            # Boundary 2: event classification — assert all fields appear on one line
            assert any(
                "MatrixChannel: classify event=" in line
                and " class=" in line
                and " msgtype=" in line
                and " has_url=" in line
                and " has_file_url=" in line
                and " has_key_material=" in line
                for line in log_output.splitlines()
            ), f"classify log line missing expected fields. Log output:\n{log_output}"

            # Boundary 3: policy decision — assert result= and reason= appear on one line
            assert any(
                "MatrixChannel: policy event=" in line and " result=" in line and " reason=" in line
                for line in log_output.splitlines()
            ), f"policy log line missing expected fields. Log output:\n{log_output}"

            # Boundary 4: download/decrypt branch
            assert "MatrixChannel: download event=" in log_output, (
                f"Expected 'MatrixChannel: download event=' in log output.\nGot:\n{log_output}"
            )
            assert "encrypted=" in log_output
            assert "url=" in log_output

            # Boundary 5: embed decision
            assert "MatrixChannel: embed mxc=" in log_output, (
                f"Expected 'MatrixChannel: embed mxc=' in log output.\nGot:\n{log_output}"
            )
            assert "embedded=" in log_output

        finally:
            logger.remove(sink_id)

    async def test_malformed_declared_size_does_not_block_download(self) -> None:
        """When a BadEvent has a malformed info.size, the preflight guard is skipped
        and the download is still attempted through _handle_bad_event."""
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config(group_policy="open")
        ch = MatrixChannel(config=config)
        ch._client = MagicMock()
        download_mock = AsyncMock(
            return_value=MagicMock(body=b"some file content", content_type="application/pdf")
        )
        ch._client.download = download_mock

        # BadEvent whose content has file shape but malformed size in info
        source: dict[str, Any] = {
            "sender": "@alice:example.org",
            "event_id": "$bad_size",
            "origin_server_ts": 0,
            "room_id": "!room1:example.org",
            "type": "m.room.message",
            "unsigned": {},
            "content": {
                "msgtype": "m.file",
                "body": "doc.pdf",
                "info": {"size": "not-a-number", "mimetype": "application/pdf"},
                "file": {
                    "url": "mxc://example.org/badsize123",
                    "key": {
                        "k": "base64key",
                        "kty": "oct",
                        "alg": "A256CTR",
                        "key_ops": ["encrypt", "decrypt"],
                        "ext": True,
                    },
                    "iv": "base64iv",
                    "hashes": {"sha256": "base64hash"},
                },
            },
        }
        event = nio.BadEvent(
            source=source,
            event_id="$bad_size",
            sender="@alice:example.org",
            server_timestamp=0,
            type="m.room.message",
        )

        room = MagicMock()
        room.room_id = "!room1:example.org"

        # Patch at source because matrix.py imports decrypt_attachment lazily inside the
        # function body: `from nio.crypto.attachments import decrypt_attachment`
        with patch("nio.crypto.attachments.decrypt_attachment", return_value=b"decrypted"):
            await ch._handle_bad_event(room, event)

        # Download must be attempted even when declared size is malformed
        download_mock.assert_awaited_once()
