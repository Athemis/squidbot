# Matrix Channel Adapter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a spec-compliant Matrix channel adapter (`MatrixChannel`) for squidbot.

**Architecture:** Hexagonal — `MatrixChannel` lives in `squidbot/adapters/channels/matrix.py`,
implements `ChannelPort` structurally, uses `matrix-nio` for all Matrix I/O. Core models get
two new fields (`InboundMessage.metadata`, `OutboundMessage.attachment` + `.metadata`). The
typing keepalive loop runs inside `MatrixChannel`, invisible to the core. Attachments use
`mimetypes.guess_type` for MIME (with optional `python-magic` for content-based detection),
Pillow for image dimensions, ffprobe for video/audio metadata.

**Tech Stack:** matrix-nio, mimetypes (stdlib), python-magic (optional), Pillow, ffprobe (subprocess), markdown-it-py,
asyncio, pytest + unittest.mock

**Design doc:** `docs/plans/2026-02-22-matrix-channel-design.md`

---

## Task 1: Add `metadata` to `InboundMessage` and `attachment`/`metadata` to `OutboundMessage`

**Files:**
- Modify: `squidbot/core/models.py:74-88`
- Modify: `tests/core/test_models.py` (extend existing tests)

**Step 1: Write the failing test**

Open `tests/core/test_models.py`. Add at the bottom:

```python
def test_inbound_message_metadata_default_empty():
    session = Session(channel="test", sender_id="user")
    msg = InboundMessage(session=session, text="hello")
    assert msg.metadata == {}


def test_inbound_message_metadata_custom():
    session = Session(channel="test", sender_id="user")
    msg = InboundMessage(session=session, text="hi", metadata={"matrix_event_id": "$abc"})
    assert msg.metadata["matrix_event_id"] == "$abc"


def test_outbound_message_attachment_default_none():
    session = Session(channel="test", sender_id="user")
    msg = OutboundMessage(session=session, text="hi")
    assert msg.attachment is None
    assert msg.metadata == {}


def test_outbound_message_attachment_set():
    from pathlib import Path
    session = Session(channel="test", sender_id="user")
    msg = OutboundMessage(session=session, text="", attachment=Path("/tmp/foo.jpg"))
    assert msg.attachment == Path("/tmp/foo.jpg")
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_models.py -v -k "metadata or attachment"
```

Expected: `AttributeError: 'InboundMessage' object has no attribute 'metadata'`

**Step 3: Add the fields to `models.py`**

In `squidbot/core/models.py`, add the import for `Path` and `Any` at the top (they're already there), then update the two dataclasses:

```python
# Change InboundMessage (around line 74) to:
@dataclass
class InboundMessage:
    """A message received from a channel."""

    session: Session
    text: str
    received_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
```

```python
# Change OutboundMessage (around line 83) to:
@dataclass
class OutboundMessage:
    """A message to be sent to a channel."""

    session: Session
    text: str
    attachment: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Also add `Path` to the imports at the top of `models.py`:

```python
from pathlib import Path
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/core/test_models.py -v
```

Expected: all PASS

**Step 5: Run full suite to check nothing broke**

```bash
uv run pytest -q
```

Expected: all existing tests still pass

**Step 6: Commit**

```bash
git add squidbot/core/models.py tests/core/test_models.py
git commit --no-gpg-sign -m "feat: add metadata to InboundMessage and attachment+metadata to OutboundMessage"
```

---

## Task 2: Add `room_ids` field to `MatrixChannelConfig` and new dependencies

**Files:**
- Modify: `squidbot/config/schema.py:85-93`
- Modify: `pyproject.toml`

**Step 1: Update `MatrixChannelConfig` in `schema.py`**

Current `MatrixChannelConfig` (lines 85–93):
```python
class MatrixChannelConfig(BaseModel):
    enabled: bool = False
    homeserver: str = "https://matrix.org"
    user_id: str = ""
    access_token: str = ""
    device_id: str = "SQUIDBOT01"
    allow_from: list[str] = Field(default_factory=list)
    group_policy: str = "mention"  # "open", "mention", "allowlist"
```

Replace with:
```python
class MatrixChannelConfig(BaseModel):
    """Configuration for the Matrix channel adapter."""

    enabled: bool = False
    homeserver: str = "https://matrix.org"
    user_id: str = ""
    access_token: str = ""
    device_id: str = "SQUIDBOT01"
    room_ids: list[str] = Field(default_factory=list)
    group_policy: str = "mention"  # "open", "mention", "allowlist"
    allowlist: list[str] = Field(default_factory=list)
```

Note: `allow_from` is renamed to `allowlist` and `room_ids` is added. The existing
`allow_from` field was not used anywhere yet so renaming is safe.

**Step 2: Add new dependencies to `pyproject.toml`**

In the `dependencies` list, add only `Pillow` (hard dependency for image dimensions).
`python-magic` is optional — not added to `pyproject.toml`; users can install it separately
for more accurate content-based MIME detection.

```toml
    "Pillow>=10.0",
```

**Step 3: Install new dependencies**

```bash
uv sync
```

Expected: resolves and installs `Pillow`.

**Step 4: Run full suite**

```bash
uv run pytest -q && uv run ruff check .
```

Expected: all pass, no lint errors.

**Step 5: Commit**

```bash
git add squidbot/config/schema.py pyproject.toml uv.lock
git commit --no-gpg-sign -m "feat: add room_ids+allowlist to MatrixChannelConfig, add Pillow dep"
```

---

## Task 3: Write failing tests for `MatrixChannel` — receiving messages

**Files:**
- Create: `tests/adapters/channels/test_matrix.py`

This is a TDD task. Write all the receiving-side tests first; they will fail because `MatrixChannel` doesn't exist yet.

**Step 1: Create the test file**

```python
"""Tests for MatrixChannel — receiving messages."""

from __future__ import annotations

import asyncio
from datetime import datetime
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
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/adapters/channels/test_matrix.py -v
```

Expected: `ImportError: No module named 'squidbot.adapters.channels.matrix'`

**Step 3: Commit the failing tests**

```bash
git add tests/adapters/channels/test_matrix.py
git commit --no-gpg-sign -m "test: add failing tests for MatrixChannel receive"
```

---

## Task 4: Implement `MatrixChannel` — skeleton + receiving

**Files:**
- Create: `squidbot/adapters/channels/matrix.py`

**Step 1: Create the file**

```python
"""
Matrix channel adapter for squidbot.

Implements ChannelPort using matrix-nio. Receives messages via sync_forever(),
filters them by group_policy, and queues InboundMessage instances. Sends responses
as m.room.message events with Markdown rendered to HTML.

Typing notifications use a per-room keepalive loop (25s interval, 30s server timeout).
Attachments are uploaded via the Matrix content repository and sent as typed media events.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import nio
from loguru import logger
from markdown_it import MarkdownIt

from squidbot.core.models import InboundMessage, OutboundMessage, Session

if TYPE_CHECKING:
    from squidbot.config.schema import MatrixChannelConfig


# Typing keepalive constants (Matrix spec §5.3)
_TYPING_TIMEOUT_MS: int = 30_000
_TYPING_KEEPALIVE_S: float = 25.0
_TYPING_RETRY_DEFAULT_S: float = 5.0

_md = MarkdownIt()


def _render_markdown(text: str) -> str:
    """Render Markdown to HTML for Matrix formatted_body."""
    return _md.render(text).strip()


def _detect_mime(path: Path) -> str:
    """
    Detect the MIME type of a file.

    Uses python-magic if available (content-based detection), falls back to
    mimetypes.guess_type() (extension-based) with application/octet-stream as
    final fallback.
    """
    try:
        import magic  # noqa: PLC0415

        return str(magic.from_file(str(path), mime=True))
    except ImportError:
        mime, _ = mimetypes.guess_type(path.name)
        return mime or "application/octet-stream"


def _mime_to_msgtype(mime: str) -> str:
    """Map a MIME type to a Matrix message type."""
    if mime.startswith("image/"):
        return "m.image"
    if mime.startswith("video/"):
        return "m.video"
    if mime.startswith("audio/"):
        return "m.audio"
    return "m.file"


def _image_dimensions(path: Path) -> dict[str, int]:
    """Return {'w': ..., 'h': ...} using Pillow, or {} if unavailable."""
    try:
        from PIL import Image  # noqa: PLC0415

        with Image.open(path) as img:
            w, h = img.size
            return {"w": w, "h": h}
    except Exception:  # noqa: BLE001
        return {}


def _media_metadata(path: Path, mime: str) -> dict[str, Any]:
    """
    Extract media metadata using ffprobe (video/audio) or Pillow (images).

    Returns a partial 'info' dict. Missing fields are simply omitted.
    """
    info: dict[str, Any] = {
        "mimetype": mime,
        "size": path.stat().st_size,
    }
    if mime.startswith("image/"):
        info.update(_image_dimensions(path))
    elif mime.startswith(("video/", "audio/")):
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_streams",
                    "-show_format",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            import json  # noqa: PLC0415

            data = json.loads(result.stdout)
            fmt = data.get("format", {})
            duration_s = float(fmt.get("duration", 0))
            if duration_s:
                info["duration"] = int(duration_s * 1000)  # ms
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    w = stream.get("width")
                    h = stream.get("height")
                    if w and h:
                        info["w"] = w
                        info["h"] = h
                    break
        except Exception:  # noqa: BLE001
            pass
    return info


class MatrixChannel:
    """
    Matrix channel adapter.

    Connects to a Matrix homeserver, listens for messages in configured rooms,
    and sends responses as formatted Matrix events.

    Args:
        config: MatrixChannelConfig from squidbot settings.
    """

    streaming: bool = False  # accumulate full response before sending

    def __init__(self, config: MatrixChannelConfig) -> None:
        self._config = config
        self._queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._sync_start_ms: int = int(datetime.now().timestamp() * 1000)
        # Typing state per room
        self._typing_active: dict[str, bool] = {}
        self._typing_tasks: dict[str, asyncio.Task[None]] = {}
        # nio client (created lazily in _connect)
        self._client: nio.AsyncClient | None = None

    # ── ChannelPort interface ────────────────────────────────────────────────

    async def receive(self) -> AsyncIterator[InboundMessage]:  # type: ignore[override]
        """Yield inbound messages as they arrive from Matrix."""
        await self._connect()
        assert self._client is not None
        asyncio.create_task(self._sync_loop())
        while True:
            msg = await self._queue.get()
            yield msg

    async def send(self, message: OutboundMessage) -> None:
        """Send a message (and optional attachment) to Matrix."""
        assert self._client is not None
        room_id = message.metadata.get("matrix_room_id", "")
        if not room_id:
            logger.warning("MatrixChannel.send: no matrix_room_id in metadata, dropping")
            return

        thread_root: str | None = message.metadata.get("matrix_thread_root")

        # Send attachment first if present
        if message.attachment and message.attachment.exists():
            await self._send_attachment(room_id, message.attachment, thread_root)

        # Send text (skip if empty and attachment was sent)
        if message.text or not message.attachment:
            await self._send_text(room_id, message.text, thread_root)

    async def send_typing(self, session_id: str, typing: bool = True) -> None:
        """
        Send a typing notification to Matrix with spec-compliant keepalive.

        The session_id is expected to contain the room_id as metadata is not
        available here; for Matrix the convention is "matrix:<room_id>".

        Args:
            session_id: Session identifier; room_id is extracted from metadata.
            typing: True to start typing, False to stop.
        """
        # Extract room_id from session_id ("matrix:!room:server")
        parts = session_id.split(":", 1)
        room_id = parts[1] if len(parts) == 2 else session_id

        if typing:
            await self._start_typing(room_id)
        else:
            await self._stop_typing(room_id)

    # ── Connection ───────────────────────────────────────────────────────────

    async def _connect(self) -> None:
        """Create and configure the nio AsyncClient."""
        if self._client is not None:
            return
        cfg = self._config
        client = nio.AsyncClient(
            homeserver=cfg.homeserver,
            user=cfg.user_id,
            device_id=cfg.device_id,
        )
        client.access_token = cfg.access_token
        client.user_id = cfg.user_id
        client.add_event_callback(self._handle_text, nio.RoomMessageText)
        client.add_event_callback(self._handle_media, nio.RoomMessageMedia)
        client.add_event_callback(self._handle_reaction, nio.UnknownEvent)
        self._client = client
        self._sync_start_ms = int(datetime.now().timestamp() * 1000)
        logger.info("MatrixChannel: connected as {}", cfg.user_id)

    async def _sync_loop(self) -> None:
        """Run nio sync_forever in the background."""
        assert self._client is not None
        try:
            await self._client.sync_forever(timeout=30_000)
        except Exception as exc:  # noqa: BLE001
            logger.error("MatrixChannel: sync_forever error: {}", exc)

    # ── Event handlers ───────────────────────────────────────────────────────

    async def _handle_text(self, room: Any, event: Any) -> None:
        """Handle an incoming m.room.message (m.text) event."""
        if not self._accept_event(room, event):
            return
        text: str = getattr(event, "body", "")
        metadata = self._extract_metadata(event)
        session = Session(channel="matrix", sender_id=event.sender)
        self._queue.put_nowait(InboundMessage(session=session, text=text, metadata=metadata))

    async def _handle_media(self, room: Any, event: Any) -> None:
        """Handle an incoming m.room.message with a media msgtype."""
        if not self._accept_event(room, event):
            return
        assert self._client is not None
        try:
            text = await self._download_attachment(event)
        except Exception as exc:  # noqa: BLE001
            text = f"[Anhang nicht verfügbar: {exc}]"
        metadata = self._extract_metadata(event)
        session = Session(channel="matrix", sender_id=event.sender)
        self._queue.put_nowait(InboundMessage(session=session, text=text, metadata=metadata))

    async def _handle_reaction(self, room: Any, event: Any) -> None:
        """Handle m.reaction events — incoming emoji reactions."""
        content = getattr(event, "source", {}).get("content", {})
        if content.get("type") == "m.reaction" or (
            isinstance(content.get("m.relates_to"), dict)
            and content["m.relates_to"].get("rel_type") == "m.annotation"
        ):
            sender = getattr(event, "sender", "")
            if sender == self._config.user_id:
                return
            key = content.get("m.relates_to", {}).get("key", "?")
            room_id = getattr(room, "room_id", "")
            metadata = {"matrix_room_id": room_id, "matrix_event_id": getattr(event, "event_id", "")}
            session = Session(channel="matrix", sender_id=sender)
            self._queue.put_nowait(
                InboundMessage(session=session, text=f"[Reaktion: {key}]", metadata=metadata)
            )

    # ── Filtering helpers ────────────────────────────────────────────────────

    def _accept_event(self, room: Any, event: Any) -> bool:
        """Return True if the event should be processed."""
        # Skip own messages
        if getattr(event, "sender", "") == self._config.user_id:
            return False
        # Skip events older than sync start (historic backfill)
        ts = getattr(event, "server_timestamp", 0)
        if ts and ts < self._sync_start_ms:
            return False
        # Skip rooms not in configured list
        room_id = getattr(event, "room_id", getattr(room, "room_id", ""))
        if self._config.room_ids and room_id not in self._config.room_ids:
            return False
        sender: str = getattr(event, "sender", "")
        body: str = getattr(event, "body", "")
        policy = self._config.group_policy
        if policy == "open":
            return True
        if policy == "mention":
            return self._config.user_id in body
        if policy == "allowlist":
            return sender in self._config.allowlist
        return False

    def _extract_metadata(self, event: Any) -> dict[str, Any]:
        """Extract Matrix-specific metadata from an event."""
        meta: dict[str, Any] = {
            "matrix_event_id": getattr(event, "event_id", ""),
            "matrix_room_id": getattr(event, "room_id", ""),
        }
        relates_to = event.source.get("content", {}).get("m.relates_to", {})
        if relates_to.get("rel_type") == "m.thread":
            meta["matrix_thread_root"] = relates_to["event_id"]
        return meta

    # ── Sending helpers ──────────────────────────────────────────────────────

    async def _send_text(self, room_id: str, text: str, thread_root: str | None) -> None:
        """Send a text message to Matrix with optional thread context."""
        assert self._client is not None
        content: dict[str, Any] = {
            "msgtype": "m.text",
            "body": text,
            "format": "org.matrix.custom.html",
            "formatted_body": _render_markdown(text),
            "m.mentions": {},
        }
        if thread_root:
            content["m.relates_to"] = {
                "rel_type": "m.thread",
                "event_id": thread_root,
                "m.in_reply_to": {"event_id": thread_root},
                "is_falling_back": True,
            }
        resp = await self._client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )
        if isinstance(resp, nio.RoomSendError):
            logger.error("MatrixChannel: send error in {}: {}", room_id, resp)

    async def _send_attachment(
        self, room_id: str, path: Path, thread_root: str | None
    ) -> None:
        """Upload a file and send it as a typed media event."""
        assert self._client is not None
        mime: str = _detect_mime(path)
        msgtype = _mime_to_msgtype(mime)
        info = _media_metadata(path, mime)

        data = path.read_bytes()
        resp = await self._client.upload(
            data_provider=lambda *_: data,
            content_type=mime,
            filename=path.name,
            filesize=len(data),
        )
        if isinstance(resp, tuple):
            upload_resp, _ = resp
        else:
            upload_resp = resp
        if isinstance(upload_resp, nio.UploadError):
            logger.error("MatrixChannel: upload failed: {}", upload_resp)
            return
        mxc_uri: str = upload_resp.content_uri

        content: dict[str, Any] = {
            "msgtype": msgtype,
            "body": path.name,
            "filename": path.name,
            "url": mxc_uri,
            "info": info,
            "m.mentions": {},
        }
        if thread_root:
            content["m.relates_to"] = {
                "rel_type": "m.thread",
                "event_id": thread_root,
                "m.in_reply_to": {"event_id": thread_root},
                "is_falling_back": True,
            }
        resp2 = await self._client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )
        if isinstance(resp2, nio.RoomSendError):
            logger.error("MatrixChannel: media send error in {}: {}", room_id, resp2)

    # ── Attachment download ──────────────────────────────────────────────────

    async def _download_attachment(self, event: Any) -> str:
        """
        Download an incoming media attachment and return a text description.

        Saves the file to /tmp/squidbot-<sha256[:8]>.<ext>.
        """
        assert self._client is not None
        mxc: str = getattr(event, "url", "") or ""
        enc_file = getattr(event, "file", None)
        if enc_file:
            mxc = enc_file.url

        # Parse mxc://server/mediaid
        if not mxc.startswith("mxc://"):
            return "[Anhang: ungültige mxc URI]"
        mxc_body = mxc[len("mxc://"):]
        server, _, media_id = mxc_body.partition("/")

        resp = await self._client.download(server_name=server, media_id=media_id)
        if isinstance(resp, nio.DownloadError):
            return f"[Anhang nicht verfügbar: {resp.message}]"

        body: bytes = resp.body

        # Decrypt if E2EE
        if enc_file is not None:
            from nio.crypto.attachments import decrypt_attachment  # noqa: PLC0415

            key_info = {
                "url": enc_file.url,
                "key": {
                    "kty": enc_file.key.key_type,
                    "alg": enc_file.key.alg,
                    "k": enc_file.key.k,
                    "key_ops": enc_file.key.key_ops,
                    "ext": enc_file.key.ext,
                },
                "iv": enc_file.iv,
                "hashes": enc_file.hashes,
                "v": enc_file.v,
            }
            body = decrypt_attachment(body, key_info)

        # Determine extension
        info = getattr(event, "info", None)
        mimetype = (info.mimetype if info else None) or resp.content_type or ""
        ext = mimetypes.guess_extension(mimetype) or ""

        # Save to temp file
        sha = hashlib.sha256(body).hexdigest()[:8]
        tmp_path = Path(f"/tmp/squidbot-{sha}{ext}")
        tmp_path.write_bytes(body)

        filename = getattr(event, "body", path.name if hasattr(event, "path") else "attachment")
        return f"[Anhang: {filename} ({mimetype})] → {tmp_path}"

    # ── Typing keepalive ─────────────────────────────────────────────────────

    async def _start_typing(self, room_id: str) -> None:
        """Start the typing keepalive loop for a room."""
        # Cancel any existing task for this room
        old_task = self._typing_tasks.get(room_id)
        if old_task and not old_task.done():
            old_task.cancel()
            try:
                await old_task
            except asyncio.CancelledError:
                pass

        self._typing_active[room_id] = True
        task = asyncio.create_task(self._typing_keepalive_loop(room_id))
        self._typing_tasks[room_id] = task

    async def _stop_typing(self, room_id: str) -> None:
        """Stop the typing keepalive loop and send a stop-typing event."""
        self._typing_active[room_id] = False
        task = self._typing_tasks.pop(room_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._client:
            try:
                await self._client.room_typing(room_id, typing_state=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("MatrixChannel: stop-typing error in {}: {}", room_id, exc)

    async def _typing_keepalive_loop(self, room_id: str) -> None:
        """
        Repeatedly send typing=True until _typing_active[room_id] is False.

        Sends every TYPING_KEEPALIVE_S seconds (= TYPING_TIMEOUT_MS - 5s margin).
        Handles 429 rate-limiting by sleeping for retry_after_ms.
        """
        assert self._client is not None
        while self._typing_active.get(room_id):
            try:
                resp = await self._client.room_typing(
                    room_id, typing_state=True, timeout=_TYPING_TIMEOUT_MS
                )
                if isinstance(resp, nio.RoomTypingError):
                    if hasattr(resp, "retry_after_ms") and resp.retry_after_ms:
                        retry_s = resp.retry_after_ms / 1000
                    else:
                        retry_s = _TYPING_RETRY_DEFAULT_S
                    logger.warning(
                        "MatrixChannel: typing rate-limited in {}, retry in {}s",
                        room_id,
                        retry_s,
                    )
                    await asyncio.sleep(retry_s)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("MatrixChannel: typing error in {}: {}", room_id, exc)
                break
            await asyncio.sleep(_TYPING_KEEPALIVE_S)
```

Note: `receive()` has a type ignore comment because nio callbacks are synchronous
while ChannelPort.receive() is an async generator — the structural match still holds.

**Step 2: Fix the `AsyncIterator` return type**

The `receive()` method needs a proper async generator signature. Python's type system
requires `async def receive(self) -> AsyncIterator[...]` to be an async generator
function. Change it to use `yield`:

```python
async def receive(self) -> AsyncIterator[InboundMessage]:
    """Yield inbound messages as they arrive from Matrix."""
    await self._connect()
    assert self._client is not None
    asyncio.create_task(self._sync_loop())
    while True:
        msg = await self._queue.get()
        yield msg
```

Also add `from collections.abc import AsyncIterator` to the imports.

**Step 3: Run the receive tests**

```bash
uv run pytest tests/adapters/channels/test_matrix.py::TestMatrixChannelReceive -v
```

Expected: most tests PASS. Fix any import errors.

**Step 4: Run ruff and mypy**

```bash
uv run ruff check squidbot/adapters/channels/matrix.py
uv run mypy squidbot/adapters/channels/matrix.py
```

Fix all reported errors.

**Step 5: Run full suite**

```bash
uv run pytest -q
```

Expected: all pass.

**Step 6: Commit**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit --no-gpg-sign -m "feat: implement MatrixChannel receive (text events, group_policy, thread metadata)"
```

---

## Task 5: Write and pass tests for typing keepalive

**Files:**
- Modify: `tests/adapters/channels/test_matrix.py`

**Step 1: Add typing tests**

```python
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

        await ch.send_typing("matrix:!room1:example.org", typing=True)
        await asyncio.sleep(0)  # let the event loop tick

        assert "!room1:example.org" in ch._typing_tasks
        assert not ch._typing_tasks["!room1:example.org"].done()

        # Cleanup
        await ch.send_typing("matrix:!room1:example.org", typing=False)

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

        await ch.send_typing("matrix:!room1:example.org", typing=True)
        await asyncio.sleep(0)
        await ch.send_typing("matrix:!room1:example.org", typing=False)
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

        original = matrix_mod._TYPING_KEEPALIVE_S
        matrix_mod._TYPING_KEEPALIVE_S = 0.05  # speed up test

        try:
            await ch.send_typing("matrix:!room1:example.org", typing=True)
            await asyncio.sleep(0.2)  # enough for 2+ keepalive ticks
            assert call_count >= 2
        finally:
            matrix_mod._TYPING_KEEPALIVE_S = original
            await ch.send_typing("matrix:!room1:example.org", typing=False)

    @pytest.mark.asyncio
    async def test_typing_429_retries_after_delay(self) -> None:
        """Keepalive loop sleeps for retry_after_ms on 429 and retries."""
        from squidbot.adapters.channels import matrix as matrix_mod
        from squidbot.adapters.channels.matrix import MatrixChannel

        config = _make_config()
        ch = MatrixChannel(config=config)
        call_count = 0

        rate_limit_resp = MagicMock(spec=nio.RoomTypingError)
        rate_limit_resp.retry_after_ms = 50  # 50ms retry

        ok_resp = MagicMock()
        # First call returns 429, subsequent calls succeed
        responses = [rate_limit_resp, ok_resp, ok_resp, ok_resp]

        async def fake_room_typing(room_id: str, typing_state: bool, timeout: int = 0) -> Any:
            nonlocal call_count
            if typing_state:
                call_count += 1
                if responses:
                    return responses.pop(0)
            return MagicMock()

        ch._client = MagicMock()
        ch._client.room_typing = fake_room_typing

        original = matrix_mod._TYPING_KEEPALIVE_S
        matrix_mod._TYPING_KEEPALIVE_S = 0.01

        try:
            await ch.send_typing("matrix:!room1:example.org", typing=True)
            await asyncio.sleep(0.3)
            # Should have retried after the 429
            assert call_count >= 2
        finally:
            matrix_mod._TYPING_KEEPALIVE_S = original
            await ch.send_typing("matrix:!room1:example.org", typing=False)
```

**Step 2: Run the typing tests**

```bash
uv run pytest tests/adapters/channels/test_matrix.py::TestMatrixChannelTyping -v
```

Fix any failures. Common issue: `nio.RoomTypingError` mock — use `spec=nio.RoomTypingError`
only if that class exists in the nio version installed.

**Step 3: Run full suite**

```bash
uv run pytest -q
```

**Step 4: Commit**

```bash
git add tests/adapters/channels/test_matrix.py squidbot/adapters/channels/matrix.py
git commit --no-gpg-sign -m "test: add typing keepalive tests for MatrixChannel"
```

---

## Task 6: Write and pass tests for `send()` (text + attachments)

**Files:**
- Modify: `tests/adapters/channels/test_matrix.py`

**Step 1: Add send tests**

```python
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

        async def fake_room_send(room_id: str, message_type: str, content: dict[str, Any]) -> MagicMock:
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

        async def fake_room_send(room_id: str, message_type: str, content: dict[str, Any]) -> MagicMock:
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
    async def test_send_attachment_uploads_and_sends_media_event(
        self, tmp_path: Path
    ) -> None:
        """send() with attachment uploads the file and sends a media event."""
        import struct
        from squidbot.adapters.channels.matrix import MatrixChannel
        from squidbot.core.models import OutboundMessage, Session

        # Create a minimal valid JPEG (enough for magic to detect)
        jpg = tmp_path / "test.jpg"
        jpg.write_bytes(
            b"\xff\xd8\xff\xe0" + b"\x00" * 10 + b"\xff\xd9"  # minimal JPEG
        )

        config = _make_config()
        ch = MatrixChannel(config=config)
        sent: list[dict[str, Any]] = []

        async def fake_upload(data_provider: Any, content_type: str, filename: str, filesize: int) -> tuple[MagicMock, Any]:
            resp = MagicMock()
            resp.content_uri = "mxc://example.org/TestMediaId"
            return resp, None

        async def fake_room_send(room_id: str, message_type: str, content: dict[str, Any]) -> MagicMock:
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

        with patch("mimetypes.guess_type", return_value=("image/jpeg", None)):
            await ch.send(msg)

        # Should have sent one media event
        media_events = [e for e in sent if e.get("msgtype") == "m.image"]
        assert len(media_events) == 1
        assert media_events[0]["url"] == "mxc://example.org/TestMediaId"
        assert media_events[0]["filename"] == "test.jpg"
```

**Step 2: Run send tests**

```bash
uv run pytest tests/adapters/channels/test_matrix.py::TestMatrixChannelSend -v
```

Fix failures. The attachment test patches `mimetypes.guess_type` (the stdlib fallback)
so no real file analysis is needed. If `python-magic` is installed in the test environment,
patch `squidbot.adapters.channels.matrix.magic.from_file` instead.

**Step 3: Run full suite + lint + types**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy squidbot/
```

**Step 4: Commit**

```bash
git add tests/adapters/channels/test_matrix.py squidbot/adapters/channels/matrix.py
git commit --no-gpg-sign -m "test: add send() tests for MatrixChannel (text, thread, attachment)"
```

---

## Task 7: Wire `MatrixChannel` into `_run_gateway()` in `main.py`

**Files:**
- Modify: `squidbot/cli/main.py:371-445`

**Step 1: Add `_channel_loop` helper and Matrix wiring**

After the existing `_run_gateway` function body's setup (around line 417, after
`channel_registry: dict[str, object] = {}`), add the Matrix channel:

```python
async def _channel_loop(channel: ChannelPort, loop: AgentLoop) -> None:
    """
    Drive a single channel: receive messages and run the agent for each.

    Args:
        channel: The channel adapter to drive.
        loop: The agent loop to handle each message.
    """
    async for inbound in channel.receive():
        await loop.run(inbound.session, inbound.text, channel)
```
```

This helper goes at module level (before `_run_gateway`), not nested inside it.

Then inside `_run_gateway`, after `channel_registry: dict[str, object] = {}`, add:

```python
    channel_tasks: list[asyncio.Task[None]] = []

    if settings.channels.matrix.enabled:
        from squidbot.adapters.channels.matrix import MatrixChannel  # noqa: PLC0415

        matrix_ch = MatrixChannel(config=settings.channels.matrix)
        channel_registry["matrix"] = matrix_ch
        logger.info("matrix channel: starting")
        channel_tasks.append(asyncio.create_task(_channel_loop(matrix_ch, agent_loop)))
    else:
        logger.info("matrix channel: disabled")
```

And in the `async with asyncio.TaskGroup() as tg:` block, add:

```python
            for task in channel_tasks:
                tg.create_task(asyncio.shield(task))
```

Wait — actually `TaskGroup` doesn't take pre-created tasks. Refactor:

Replace the entire `try:` block at the end of `_run_gateway` with:

```python
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(scheduler.run(on_due=on_cron_due))
            tg.create_task(heartbeat.run())
            if settings.channels.matrix.enabled:
                from squidbot.adapters.channels.matrix import MatrixChannel  # noqa: PLC0415

                matrix_ch = MatrixChannel(config=settings.channels.matrix)
                channel_registry["matrix"] = matrix_ch
                logger.info("matrix channel: starting")
                tg.create_task(_channel_loop(matrix_ch, agent_loop))
            else:
                logger.info("matrix channel: disabled")
    finally:
        for conn in mcp_connections:
            await conn.close()
```

**Step 2: Add the `_channel_loop` helper function**

Add this function just before `_run_gateway` (around line 371):

```python
async def _channel_loop(channel: ChannelPort, loop: AgentLoop) -> None:
    """
    Drive a single channel: receive messages and run the agent for each.

    Args:
        channel: The channel adapter to drive.
        loop: The agent loop to handle each message.
    """
    async for inbound in channel.receive():
        await loop.run(inbound.session, inbound.text, channel)
```

Note: `AgentLoop` is only in TYPE_CHECKING, so import it lazily:
```python
async def _channel_loop(channel: ChannelPort, loop: Any) -> None:
```

Or keep the `TYPE_CHECKING` import and annotate with string. Use `Any` for simplicity.

**Step 3: Run full suite**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy squidbot/
```

**Step 4: Commit**

```bash
git add squidbot/cli/main.py
git commit --no-gpg-sign -m "feat: wire MatrixChannel into gateway _run_gateway()"
```

---

## Task 8: Update `send_typing` in `AgentLoop` to pass room info

The current `ChannelPort.send_typing(session_id: str)` signature passes only `session_id`.
The Matrix channel's `send_typing` reconstructs the room_id from `session_id`. However,
`AgentLoop` calls `send_typing(session.id)` where `session.id` is `f"{channel}:{sender_id}"`.

For Matrix sessions, `sender_id` is the user's Matrix ID (`@alice:example.org`), not the room.
We need to pass the room_id separately. Check how `AgentLoop` calls `send_typing`.

**Step 1: Read the current AgentLoop**

```bash
grep -n "send_typing" squidbot/core/agent.py
```

**Step 2: Check how `run()` is called with Matrix metadata**

The `AgentLoop.run(session, text, channel)` is called in `_channel_loop` with
`inbound.session` — which for Matrix is `Session(channel="matrix", sender_id="@alice:example.org")`.

The typing keepalive needs the room_id, not the sender_id. Options:
1. Pass `inbound.metadata` to `run()` and let it extract room info
2. Encode room_id in the `Session.sender_id` for Matrix
3. Pass `inbound` directly to `run()`

**Recommended approach:** Update `_channel_loop` to pass `inbound.metadata["matrix_room_id"]`
as the `session_id` argument to `send_typing`. But `send_typing` is called by `AgentLoop`
internally using `session.id`.

**Simplest fix:** For Matrix, set `Session.sender_id = room_id + ":" + user_id`, or store
room_id in `Session.channel` as `"matrix:!room1:example.org"`.

Update `_handle_text` and `_handle_media` in `MatrixChannel`:

```python
# In _handle_text and _handle_media, change:
session = Session(channel="matrix", sender_id=event.sender)
# to:
room_id = getattr(event, "room_id", getattr(room, "room_id", ""))
session = Session(channel=f"matrix:{room_id}", sender_id=event.sender)
```

Then in `send_typing`, the `session_id` will be `"matrix:!room1:example.org:@alice:example.org"`.
Update the parsing in `send_typing`:

```python
async def send_typing(self, session_id: str, typing: bool = True) -> None:
    # session_id format: "matrix:!room:server:@user:server" or "matrix:!room:server"
    parts = session_id.split(":", 1)
    room_id = parts[1] if len(parts) >= 2 else session_id
    # room_id may contain the sender_id appended — strip it at the ":" before "@"
    # Simpler: session_id is "matrix:{room_id}" since Session.channel = f"matrix:{room_id}"
    # and session.id = f"{channel}:{sender_id}" = f"matrix:{room_id}:@alice:example.org"
    # Extract room_id as the part between "matrix:" and ":@"
    channel_part = session_id.removeprefix("matrix:")
    at_idx = channel_part.find(":@")
    room_id = channel_part[:at_idx] if at_idx != -1 else channel_part
    ...
```

This is getting complex. **Simpler approach:** Don't use `session_id` at all for room
routing. Instead, store the room_id in `MatrixChannel._current_room_id` and update it
when `send()` is called. Since `streaming=False`, `send()` is always called once per
conversation turn, right after `send_typing(False)`.

**Simplest approach that avoids changing core:** Store room_id in a dict keyed by
session.id in `MatrixChannel`:

```python
# In _handle_text:
session = Session(channel="matrix", sender_id=event.sender)
self._session_rooms[session.id] = room_id
```

```python
# In send_typing:
async def send_typing(self, session_id: str, typing: bool = True) -> None:
    room_id = self._session_rooms.get(session_id)
    if room_id is None:
        return  # no room known for this session yet
    ...
```

Add `self._session_rooms: dict[str, str] = {}` to `__init__`.

**Step 3: Implement the chosen approach**

Update `MatrixChannel.__init__`, `_handle_text`, `_handle_media`, `_handle_reaction`,
and `send_typing` as described above.

**Step 4: Run full suite**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy squidbot/
```

**Step 5: Commit**

```bash
git add squidbot/adapters/channels/matrix.py
git commit --no-gpg-sign -m "fix: route send_typing to correct Matrix room via session_rooms dict"
```

---

## Task 9: Final verification

**Step 1: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all tests pass (previously 147 + new matrix tests).

**Step 2: Run linter**

```bash
uv run ruff check .
```

Expected: no errors.

**Step 3: Run type checker**

```bash
uv run mypy squidbot/
```

Expected: 0 errors.

**Step 4: Reinstall CLI**

```bash
uv tool install --reinstall /home/alex/git/squidbot
```

**Step 5: Final commit (if any files unstaged)**

```bash
git status
git add -A
git commit --no-gpg-sign -m "chore: final cleanup for Matrix channel adapter"
```
