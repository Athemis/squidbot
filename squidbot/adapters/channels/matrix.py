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
import contextlib
import hashlib
import mimetypes
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import mistune
import nio
from loguru import logger

from squidbot.core.models import InboundMessage, OutboundMessage, Session

if TYPE_CHECKING:
    from squidbot.config.schema import MatrixChannelConfig


# Typing keepalive constants (Matrix spec §5.3)
_TYPING_TIMEOUT_MS: int = 30_000
_TYPING_KEEPALIVE_S: float = 25.0
_TYPING_RETRY_DEFAULT_S: float = 5.0

_md = mistune.create_markdown(escape=True)


def _render_markdown(text: str) -> str:
    """Render Markdown to HTML for Matrix formatted_body."""
    rendered = cast(str, _md(text))
    return rendered.strip()


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


async def _media_metadata(path: Path, mime: str) -> dict[str, Any]:
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
            proc = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                return info
            import json  # noqa: PLC0415

            data = json.loads(stdout.decode("utf-8"))
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
        """Initialize MatrixChannel with the given configuration."""
        self._config = config
        self._queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._sync_start_ms: int = int(datetime.now().timestamp() * 1000)
        # Typing state per room
        self._typing_active: dict[str, bool] = {}
        self._typing_tasks: dict[str, asyncio.Task[None]] = {}
        # Session → room_id mapping for send_typing routing
        self._session_rooms: dict[str, str] = {}
        # nio client (created lazily in _connect)
        self._client: nio.AsyncClient | None = None

    # ── ChannelPort interface ────────────────────────────────────────────────

    async def receive(self) -> AsyncIterator[InboundMessage]:
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
        if not isinstance(room_id, str) or not room_id:
            logger.warning("MatrixChannel.send: no matrix_room_id in metadata, dropping")
            return

        thread_root_raw = message.metadata.get("matrix_thread_root")
        thread_root: str | None = thread_root_raw if isinstance(thread_root_raw, str) else None

        # Send attachment first if present
        if message.attachment and message.attachment.exists():
            await self._send_attachment(room_id, message.attachment, thread_root)

        # Send text (skip if empty and attachment was sent)
        if message.text or not message.attachment:
            await self._send_text(room_id, message.text, thread_root)

    async def send_typing(self, session_id: str, typing: bool = True) -> None:
        """
        Send a typing notification to Matrix with spec-compliant keepalive.

        Looks up the room_id via the session_rooms dict populated during receive().

        Args:
            session_id: Session identifier used to look up the room_id.
            typing: True to start typing, False to stop.
        """
        room_id = self._session_rooms.get(session_id)
        if room_id is None:
            return  # no room known for this session yet

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
        room_id: str = getattr(event, "room_id", getattr(room, "room_id", ""))
        self._session_rooms[session.id] = room_id
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
        room_id: str = getattr(event, "room_id", getattr(room, "room_id", ""))
        self._session_rooms[session.id] = room_id
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
            metadata: dict[str, Any] = {
                "matrix_room_id": room_id,
                "matrix_event_id": getattr(event, "event_id", ""),
            }
            session = Session(channel="matrix", sender_id=sender)
            self._session_rooms[session.id] = room_id
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

    async def _send_attachment(self, room_id: str, path: Path, thread_root: str | None) -> None:
        """Upload a file and send it as a typed media event."""
        assert self._client is not None
        mime: str = _detect_mime(path)
        msgtype = _mime_to_msgtype(mime)
        info = await _media_metadata(path, mime)

        data = await asyncio.to_thread(path.read_bytes)
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
        mxc_body = mxc[len("mxc://") :]
        server, _, media_id = mxc_body.partition("/")

        resp = await self._client.download(server_name=server, media_id=media_id)
        if isinstance(resp, nio.DownloadError):
            return f"[Anhang nicht verfügbar: {resp.message}]"

        body = cast(bytes, resp.body)

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
            decrypt_attachment_fn: Any = decrypt_attachment
            body = decrypt_attachment_fn(body, key_info)

        # Determine extension
        info = getattr(event, "info", None)
        mimetype = (info.mimetype if info else None) or resp.content_type or ""
        ext = mimetypes.guess_extension(mimetype) or ""

        # Save to temp file
        sha = hashlib.sha256(body).hexdigest()[:8]
        tmp_path = Path(f"/tmp/squidbot-{sha}{ext}")
        await asyncio.to_thread(tmp_path.write_bytes, body)

        filename: str = getattr(event, "body", "attachment")
        return f"[Anhang: {filename} ({mimetype})] → {tmp_path}"

    # ── Typing keepalive ─────────────────────────────────────────────────────

    async def _start_typing(self, room_id: str) -> None:
        """Start the typing keepalive loop for a room."""
        # Cancel any existing task for this room
        old_task = self._typing_tasks.get(room_id)
        if old_task and not old_task.done():
            old_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await old_task

        self._typing_active[room_id] = True
        task = asyncio.create_task(self._typing_keepalive_loop(room_id))
        self._typing_tasks[room_id] = task

    async def _stop_typing(self, room_id: str) -> None:
        """Stop the typing keepalive loop and send a stop-typing event."""
        self._typing_active[room_id] = False
        task = self._typing_tasks.pop(room_id, None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
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
