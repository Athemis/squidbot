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
import base64
import contextlib
import hashlib
import io
import mimetypes
import re
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

# Event types covered by registered nio callbacks — used for diagnostic logging so the
# two cannot silently diverge. MEDIA_EVENT_FILTER expands to RoomMessageMedia +
# RoomEncryptedMedia; BadEvent handles encrypted-upload events that fail schema validation.
_REGISTERED_EVENT_TYPES: tuple[type, ...] = (
    nio.RoomMessageText,
    nio.RoomMessageMedia,
    nio.RoomEncryptedMedia,
    nio.BadEvent,
    nio.InviteMemberEvent,
    nio.UnknownEvent,
)

# Tuple passed to add_event_callback so _handle_media fires for both plain and E2EE media.
MEDIA_EVENT_FILTER: tuple[type, type] = (nio.RoomMessageMedia, nio.RoomEncryptedMedia)

# Matrix media msgtypes whose content may carry encrypted-file key material.
MEDIA_MSGTYPES: frozenset[str] = frozenset({"m.image", "m.file", "m.audio", "m.video"})

# MIME types eligible for Base64 embedding in LLM multimodal content.
# SVG is explicitly excluded — it is XML-based and may cause provider handling issues.
EMBEDDABLE_IMAGE_MIMES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif"}
)

_md = mistune.create_markdown(escape=True)


def _is_media_shaped_bad_event(event: nio.BadEvent) -> bool:
    """Return True if a BadEvent carries encrypted-file key material (m.image/file/audio/video).

    nio cannot parse events where the client sends ``content.file`` instead of ``content.url``
    (encrypted upload shape) and returns them as BadEvent. This predicate identifies those
    so they can be routed through the media pipeline.

    Args:
        event: nio BadEvent to inspect.

    Returns:
        True when the event's content has a recognised media msgtype and a non-empty file URL.
    """
    content = event.source.get("content", {})
    msgtype: str = content.get("msgtype", "")
    has_file_url = bool(content.get("file", {}).get("url", ""))
    return msgtype in MEDIA_MSGTYPES and has_file_url


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

    def __init__(
        self,
        config: MatrixChannelConfig,
        owner_matrix_ids: set[str] | None = None,
    ) -> None:
        """Initialize MatrixChannel with configuration and invite policy.

        Args:
            config: Matrix channel settings from application configuration.
            owner_matrix_ids: Matrix user IDs allowed to trigger invite auto-join.

        Returns:
            None.
        """
        self._config = config
        self._owner_matrix_ids = set(owner_matrix_ids or ())
        self._queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._sync_start_ms: int = int(datetime.now().timestamp() * 1000)
        # Typing state per room
        self._typing_active: dict[str, bool] = {}
        self._typing_tasks: dict[str, asyncio.Task[None]] = {}
        # Session → room_id mapping for send_typing routing
        self._session_rooms: dict[str, str] = {}
        # nio client (created lazily in _connect)
        self._client: nio.AsyncClient | None = None
        self._e2ee_available: bool = False
        self._e2ee_degraded_reason: str | None = None
        self._server_upload_limit: int | None = None  # cached homeserver cap

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
        """Send a message (and optional attachments) to Matrix."""
        assert self._client is not None
        room_id = message.metadata.get("matrix_room_id", "")
        if not isinstance(room_id, str) or not room_id:
            logger.warning("MatrixChannel.send: no matrix_room_id in metadata, dropping")
            return

        thread_root_raw = message.metadata.get("matrix_thread_root")
        thread_root: str | None = thread_root_raw if isinstance(thread_root_raw, str) else None

        # Resolve effective outbound upload limit (min of local and homeserver cap).
        effective_limit = await self._effective_outbound_limit()

        # Send each attachment first; text reply follows regardless of attachment outcome.
        for path in message.attachments:
            if not path.exists():
                continue
            try:
                file_size = path.stat().st_size
            except OSError as exc:
                logger.error("MatrixChannel: cannot stat attachment path={} err={}", path, exc)
                continue
            if file_size > effective_limit:
                logger.debug(
                    "MatrixChannel: skip outbound path={} size={} limit={} reason={}",
                    path,
                    file_size,
                    effective_limit,
                    "exceeds_outbound_limit",
                )
                continue
            try:
                await self._send_attachment(room_id, path, thread_root)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "MatrixChannel: attachment send failed path={} room={} err={}",
                    path,
                    room_id,
                    exc,
                )

        # Send text when non-empty. Text is always delivered regardless of attachment outcome.
        if message.text:
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

        client: nio.AsyncClient
        store_path, store_hardened = self._crypto_store_path(cfg.user_id)
        if store_hardened:
            try:
                e2ee_config = nio.AsyncClientConfig(encryption_enabled=True, store_sync_tokens=True)
                client = nio.AsyncClient(
                    homeserver=cfg.homeserver,
                    user=cfg.user_id,
                    device_id=cfg.device_id,
                    store_path=store_path,
                    config=e2ee_config,
                )
                self._e2ee_available = True
                self._e2ee_degraded_reason = None
            except (AttributeError, ImportError, ImportWarning) as exc:
                self._e2ee_available = False
                self._e2ee_degraded_reason = type(exc).__name__
                logger.warning(
                    "MatrixChannel: E2EE unavailable ({}). "
                    "Install matrix-nio[e2e] to enable encrypted DMs.",
                    self._e2ee_degraded_reason,
                )
                client = nio.AsyncClient(
                    homeserver=cfg.homeserver,
                    user=cfg.user_id,
                    device_id=cfg.device_id,
                )
        else:
            self._e2ee_available = False
            self._e2ee_degraded_reason = "CryptoStorePermissions"
            logger.warning(
                "MatrixChannel: E2EE unavailable, degrading to unencrypted mode: {}",
                self._e2ee_degraded_reason,
            )
            client = nio.AsyncClient(
                homeserver=cfg.homeserver,
                user=cfg.user_id,
                device_id=cfg.device_id,
            )

        client.access_token = cfg.access_token
        client.user_id = cfg.user_id
        if self._e2ee_available:
            try:
                client.load_store()
            except Exception as load_exc:  # noqa: BLE001
                self._e2ee_available = False
                self._e2ee_degraded_reason = f"StoreLoad:{type(load_exc).__name__}"
                logger.warning(
                    "MatrixChannel: E2EE store load failed ({}); "
                    "falling back to degraded mode — encrypted messages will be undecryptable.",
                    load_exc,
                )
        client.add_event_callback(self._handle_text, nio.RoomMessageText)
        # Register _handle_media for both plain and E2EE (Megolm-decrypted) media events.
        # MEDIA_EVENT_FILTER is a tuple so nio fires _handle_media for either type with a
        # single registration, preventing double-dispatch.
        client.add_event_callback(self._handle_media, cast(Any, MEDIA_EVENT_FILTER))
        # Register _handle_bad_event for events nio cannot parse (encrypted-upload shape).
        # cast(Any, ...) on the callback silences the contravariant signature mismatch —
        # nio dispatches BadEvent at runtime but the static type expects the wide Event type.
        client.add_event_callback(cast(Any, self._handle_bad_event), cast(Any, nio.BadEvent))
        # matrix-nio callback typing does not accept InviteMemberEvent here, even though
        # runtime dispatch works; keep this cast as a type-checking workaround.
        client.add_event_callback(self._handle_invite, cast(Any, nio.InviteMemberEvent))
        # Keep UnknownEvent for reaction parsing and encrypted-event diagnostics.
        client.add_event_callback(self._handle_reaction, nio.UnknownEvent)
        # Log using _REGISTERED_EVENT_TYPES so the diagnostic cannot diverge from reality.
        logger.debug(
            "MatrixChannel: registered callbacks classes={}",
            [c.__name__ for c in _REGISTERED_EVENT_TYPES],
        )
        self._client = client
        self._sync_start_ms = int(datetime.now().timestamp() * 1000)
        logger.info("MatrixChannel: connected as {}", cfg.user_id)

    async def _sync_loop(self) -> None:
        """Run nio sync_forever in the background."""
        assert self._client is not None
        try:
            snapshot = await self._client.sync(timeout=30_000, full_state=True)
            if isinstance(snapshot, nio.SyncError):
                logger.warning("MatrixChannel: initial sync failed: {}", snapshot)
            else:
                self._log_room_membership_snapshot()
            if self._e2ee_available:
                logger.info("MatrixChannel: E2EE readiness=enabled")
            else:
                logger.warning(
                    "MatrixChannel: E2EE readiness=degraded reason={}",
                    self._e2ee_degraded_reason or "unknown",
                )
            await self._client.sync_forever(timeout=30_000, full_state=True)
            logger.warning("MatrixChannel: sync_forever returned unexpectedly")
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
        event_id = getattr(event, "event_id", "?")
        event_class = type(event).__name__
        content = getattr(event, "source", {}).get("content", {})
        msgtype = content.get("msgtype") or getattr(event, "msgtype", "")
        has_url = bool(getattr(event, "url", None))
        enc_file = getattr(event, "file", None)
        has_file_url = bool(enc_file and getattr(enc_file, "url", None))
        has_key_material = bool(
            enc_file and getattr(enc_file, "key", None) and getattr(enc_file.key, "k", None)
        )
        logger.debug(
            "MatrixChannel: classify event={} class={} msgtype={} has_url={}"
            " has_file_url={} has_key_material={}",
            event_id,
            event_class,
            msgtype,
            has_url,
            has_file_url,
            has_key_material,
        )
        accepted = self._accept_event(room, event)
        if accepted:
            policy_result = "accepted"
            policy_reason = "accepted"
        else:
            policy_result = "rejected"
            policy_reason = "policy_filtered"
        logger.debug(
            "MatrixChannel: policy event={} result={} reason={}",
            event_id,
            policy_result,
            policy_reason,
        )
        if not accepted:
            return
        assert self._client is not None
        try:
            text, multimodal_content = await self._download_attachment(event)
        except Exception as exc:  # noqa: BLE001
            text = f"[Anhang nicht verfügbar: {exc}]"
            multimodal_content = None
        self._enqueue_media_message(room, event, text, multimodal_content)

    def _enqueue_media_message(
        self,
        room: Any,
        event: Any,
        text: str,
        multimodal_content: list[dict[str, Any]] | None,
    ) -> None:
        """Build an InboundMessage from a processed media event and add it to the queue.

        Shared by _handle_media and _handle_bad_event to avoid duplicate queue-building logic.

        Args:
            room: The Matrix room the event was received in.
            event: The media event (RoomMessageMedia, RoomEncryptedMedia, or BadEvent).
            text: Text description of the attachment (path or error marker).
            multimodal_content: Optional multimodal blocks for embeddable images.
        """
        metadata = self._extract_metadata(event)
        session = Session(channel="matrix", sender_id=event.sender)
        room_id: str = getattr(event, "room_id", getattr(room, "room_id", ""))
        self._session_rooms[session.id] = room_id
        self._queue.put_nowait(
            InboundMessage(
                session=session,
                text=text,
                metadata=metadata,
                multimodal_content=multimodal_content,
            )
        )

    async def _handle_reaction(self, room: Any, event: Any) -> None:
        """Handle m.reaction events — incoming emoji reactions."""
        event_source = getattr(event, "source", {})
        event_type = event_source.get("type", "")
        logger.debug(
            "MatrixChannel: _handle_reaction called type={} sender={} room={}",
            event_type,
            getattr(event, "sender", "?"),
            getattr(event, "room_id", getattr(room, "room_id", "?")),
        )
        if event_type == "m.room.encrypted":
            room_id = getattr(room, "room_id", getattr(event, "room_id", ""))
            sender = getattr(event, "sender", "")
            event_id = getattr(event, "event_id", "")
            algorithm = event_source.get("content", {}).get("algorithm", "")
            logger.warning(
                "MatrixChannel: encrypted event received room={} sender={} event={} algorithm={}",
                room_id,
                sender,
                event_id,
                algorithm,
            )
            if not self._e2ee_available:
                logger.error(
                    "MatrixChannel: encrypted event while E2EE degraded room={} sender={} event={}",
                    room_id,
                    sender,
                    event_id,
                )
            return

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

    async def _handle_bad_event(self, room: nio.MatrixRoom, event: nio.BadEvent) -> None:
        """Route media-shaped BadEvent into the media pipeline; ignore all others.

        nio returns BadEvent when it cannot parse an event against its schema.
        This happens for encrypted uploads where the client sends ``content.file``
        instead of ``content.url`` — the schema validator rejects them. We detect
        such events via _is_media_shaped_bad_event and delegate to the shared
        media processing path.

        Args:
            room: The Matrix room the event was received in.
            event: The BadEvent to inspect and potentially route.
        """
        if not _is_media_shaped_bad_event(event):
            return
        if not self._accept_event(room, event):
            return
        assert self._client is not None
        try:
            text, multimodal_content = await self._download_attachment(event)
        except Exception as exc:  # noqa: BLE001
            text = f"[Anhang nicht verfügbar: {exc}]"
            multimodal_content = None
        self._enqueue_media_message(room, event, text, multimodal_content)

    async def _handle_invite(self, room: Any, event: Any) -> None:
        """Auto-join invitations from allowlisted owner Matrix IDs."""
        if self._client is None:
            return

        membership = getattr(event, "membership", "")
        if membership != "invite":
            return

        state_key = getattr(event, "state_key", "")
        if state_key != self._config.user_id:
            return

        sender = getattr(event, "sender", "")
        if sender not in self._owner_matrix_ids:
            logger.info("MatrixChannel: ignore invite from non-owner {}", sender)
            return

        room_id = getattr(room, "room_id", getattr(event, "room_id", ""))
        if not room_id:
            logger.warning("MatrixChannel: invite missing room_id from inviter {}", sender)
            return

        try:
            join_resp = await self._client.join(room_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "MatrixChannel: auto-join exception room={} inviter={} err={}",
                room_id,
                sender,
                exc,
            )
            return

        if isinstance(join_resp, nio.JoinError):
            logger.error(
                "MatrixChannel: auto-join failed room={} inviter={} err={}",
                room_id,
                sender,
                join_resp,
            )
            return

        logger.info("MatrixChannel: auto-joined invited room {} from owner {}", room_id, sender)

    # ── Filtering helpers ────────────────────────────────────────────────────

    def _accept_event(self, room: Any, event: Any) -> bool:
        """Return True if the event should be processed."""
        sender: str = getattr(event, "sender", "")
        room_id = getattr(event, "room_id", getattr(room, "room_id", ""))
        event_id = getattr(event, "event_id", "")
        # Skip own messages
        if sender == self._config.user_id:
            logger.debug("MatrixChannel: drop own event={} room={}", event_id, room_id)
            return False
        # Skip events older than sync start (historic backfill)
        ts = getattr(event, "server_timestamp", 0)
        if ts and ts < self._sync_start_ms:
            logger.debug(
                "MatrixChannel: drop old event={} room={} ts={} sync_start={}",
                event_id,
                room_id,
                ts,
                self._sync_start_ms,
            )
            return False
        # Skip rooms not in configured list
        if self._config.room_ids and room_id not in self._config.room_ids:
            logger.debug("MatrixChannel: drop room filter event={} room={}", event_id, room_id)
            return False
        # Media events have filenames (e.g. "photo.jpg") as their body, which never contains
        # an @mention. Skip the mention check for all media msgtypes so they are not silently
        # dropped in "mention" policy rooms.
        msgtype: str = event.source.get("content", {}).get("msgtype", "")
        if msgtype in MEDIA_MSGTYPES:
            return True  # skip mention check for all media uploads
        body: str = getattr(event, "body", "")
        policy = self._config.group_policy
        if policy == "open":
            return True
        if policy == "mention":
            accepted = self._config.user_id in body
            if not accepted:
                logger.debug(
                    "MatrixChannel: drop mention policy event={} room={} sender={}",
                    event_id,
                    room_id,
                    sender,
                )
            return accepted
        if policy == "allowlist":
            accepted = sender in self._config.allowlist
            if not accepted:
                logger.debug(
                    "MatrixChannel: drop allowlist policy event={} room={} sender={}",
                    event_id,
                    room_id,
                    sender,
                )
            return accepted
        logger.debug("MatrixChannel: drop unknown policy={} event={}", policy, event_id)
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

    def _log_room_membership_snapshot(self) -> int:
        """Warn about configured rooms the bot has not joined."""
        assert self._client is not None
        joined_room_ids = set(self._client.rooms)
        joined_count = len(joined_room_ids)

        configured = self._config.room_ids
        if not configured:
            return joined_count

        missing = [room_id for room_id in configured if room_id not in joined_room_ids]
        if missing:
            logger.warning(
                "MatrixChannel: not joined to configured room(s): {}",
                ", ".join(missing),
            )

        return joined_count

    def _crypto_store_path(self, user_id: str) -> tuple[str, bool]:
        """Build crypto-store path and report whether permissions were hardened."""
        sanitized_user_id = re.sub(r"[^A-Za-z0-9._-]", "_", user_id)
        store_dir = Path.home() / ".squidbot" / "crypto" / "matrix" / sanitized_user_id
        try:
            store_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            store_dir.chmod(0o700)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MatrixChannel: cannot harden crypto store permissions: {}", exc)
            return str(store_dir), False
        return str(store_dir), True

    # ── Sending helpers ──────────────────────────────────────────────────────

    async def _effective_outbound_limit(self) -> int:
        """Return effective outbound upload limit (min of local config and homeserver cap).

        Fetches the homeserver's upload limit once and caches it for subsequent calls.
        If the homeserver limit is unavailable or raises, only the local threshold applies.

        Returns:
            Effective upload size limit in bytes.
        """
        assert self._client is not None
        local_limit = self._config.max_outbound_upload_bytes
        if self._server_upload_limit is None:
            try:
                resp = await self._client.content_repository_config()
                server_cap = getattr(resp, "upload_size", None)
                self._server_upload_limit = (
                    int(server_cap) if server_cap is not None else local_limit
                )
            except Exception:  # noqa: BLE001
                self._server_upload_limit = local_limit
        return min(local_limit, self._server_upload_limit)

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
            ignore_unverified_devices=True,
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
        logger.debug("MatrixChannel: uploading path={} mime={} size={}", path, mime, len(data))
        resp = await self._client.upload(
            io.BytesIO(data),
            content_type=mime,
            filename=path.name,
            filesize=len(data),
        )
        if isinstance(resp, tuple):
            upload_resp, _ = resp
        else:
            upload_resp = resp
        if isinstance(upload_resp, nio.UploadError):
            logger.error("MatrixChannel: upload failed path={} err={}", path, upload_resp)
            return
        mxc_uri: str = upload_resp.content_uri
        logger.debug("MatrixChannel: uploaded path={} mxc={}", path, mxc_uri)

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
            ignore_unverified_devices=True,
        )
        if isinstance(resp2, nio.RoomSendError):
            logger.error("MatrixChannel: media send error in {}: {}", room_id, resp2)
            return
        logger.debug(
            "MatrixChannel: sent media room={} msgtype={} mxc={}", room_id, msgtype, mxc_uri
        )

    # ── Attachment download ──────────────────────────────────────────────────

    async def _download_attachment(self, event: Any) -> tuple[str, list[dict[str, Any]] | None]:
        """
        Download an incoming media attachment, apply guardrails, and optionally embed.

        For image types in EMBEDDABLE_IMAGE_MIMES whose encoded size fits within
        max_inbound_embed_bytes, returns a multimodal content list (text + image_url).
        All other files are downloaded, persisted locally, and returned as text-path only.

        Size guardrails:
        - Preflight: skip download if declared size exceeds max_inbound_download_bytes.
        - Post-fetch: discard payload if downloaded size exceeds max_inbound_download_bytes.
        - Embed gate: estimated Base64-encoded size must be <= max_inbound_embed_bytes.

        Args:
            event: nio RoomMessageMedia event (or compatible mock).

        Returns:
            Tuple of (text_description, multimodal_content_or_None).
        """
        assert self._client is not None
        mxc: str = getattr(event, "url", "") or ""
        enc_file = getattr(event, "file", None)
        if enc_file:
            mxc = enc_file.url

        # Fallback: BadEvent or event with content.file instead of content.url.
        # nio cannot parse such events and returns them with no url/file attributes;
        # extract the mxc URL directly from the event source in that case.
        source_content: dict[str, Any] = getattr(event, "source", {}).get("content", {})
        source_file: dict[str, Any] = (
            source_content.get("file", {}) if isinstance(source_content.get("file"), dict) else {}
        )
        if not mxc and enc_file is None:
            mxc = source_file.get("url", "") or ""

        # Parse mxc://server/mediaid
        if not mxc.startswith("mxc://"):
            return "[Anhang: ungültige mxc URI]", None
        mxc_body = mxc[len("mxc://") :]
        server, _, media_id = mxc_body.partition("/")

        filename: str = getattr(event, "body", "") or source_content.get("body", "attachment")
        info_obj = getattr(event, "info", None)
        declared_mime: str = (
            (getattr(info_obj, "mimetype", None) or "") if info_obj is not None else ""
        )
        if not declared_mime:
            # Try source content info for events like BadEvent
            src_info = source_content.get("info", {})
            declared_mime = src_info.get("mimetype", "") if isinstance(src_info, dict) else ""
        max_download = self._config.max_inbound_download_bytes
        max_embed = self._config.max_inbound_embed_bytes

        # Preflight: check declared size against download limit.
        if info_obj is not None:
            declared_size = getattr(info_obj, "size", None)
            if declared_size is not None:
                try:
                    ds = int(declared_size)
                except TypeError, ValueError:
                    ds = 0
                if ds > max_download:
                    logger.debug(
                        "MatrixChannel: skip download mxc={} file={} size={} reason={}",
                        mxc,
                        filename,
                        ds,
                        "exceeds_download_limit_preflight",
                    )
                    return f"[Anhang: {filename} — zu groß]", None
        # Also apply preflight guard for size declared in source content (BadEvent path).
        if info_obj is None and source_file:
            src_info = source_content.get("info", {})
            if isinstance(src_info, dict):
                src_declared_size = src_info.get("size")
                if src_declared_size is not None:
                    try:
                        src_ds = int(src_declared_size)
                    except TypeError, ValueError:
                        src_ds = 0
                    if src_ds > max_download:
                        logger.debug(
                            "MatrixChannel: skip download mxc={} file={} size={} reason={}",
                            mxc,
                            filename,
                            src_ds,
                            "exceeds_download_limit_preflight",
                        )
                        return f"[Anhang: {filename} — zu groß]", None

        event_id_val = getattr(event, "event_id", "?")
        # RoomEncryptedMedia exposes key/hashes/iv as direct event attributes.
        has_direct_enc_attrs = isinstance(getattr(event, "key", None), dict)
        is_encrypted = enc_file is not None or has_direct_enc_attrs or bool(source_file)
        logger.debug(
            "MatrixChannel: download event={} encrypted={} url={}",
            event_id_val,
            is_encrypted,
            mxc,
        )
        logger.debug("MatrixChannel: downloading mxc={} filename={}", mxc, filename)
        resp = await self._client.download(server_name=server, media_id=media_id)
        if isinstance(resp, nio.DownloadError):
            return f"[Anhang nicht verfügbar: {resp.message}]", None

        body = cast(bytes, resp.body)

        # Decrypt if E2EE via event.file (nested EncryptedFile object on the event).
        if enc_file is not None:
            from nio.crypto.attachments import decrypt_attachment  # noqa: PLC0415

            enc_key: str | None = (
                enc_file.key.get("k")
                if isinstance(enc_file.key, dict)
                else getattr(enc_file.key, "k", None)
            )
            enc_hashes = getattr(enc_file, "hashes", None)
            enc_sha256: str | None = (
                enc_hashes.get("sha256") if isinstance(enc_hashes, dict) else None
            )
            enc_iv: str | None = enc_file.iv if isinstance(enc_file.iv, str) else None
            if enc_key and enc_sha256 and enc_iv:
                body = decrypt_attachment(body, enc_key, enc_sha256, enc_iv)
            else:
                logger.warning(
                    "MatrixChannel: missing E2EE key material for event={}, skipping decrypt",
                    event_id_val,
                )
        elif has_direct_enc_attrs:
            # Decrypt via RoomEncryptedMedia direct attributes: key/hashes/iv live on the event
            # itself (parsed from content.file.* by nio), not nested under event.file.
            from nio.crypto.attachments import decrypt_attachment  # noqa: PLC0415

            direct_key_dict: dict[str, Any] = getattr(event, "key", {}) or {}
            direct_key: str | None = (
                direct_key_dict.get("k") if isinstance(direct_key_dict, dict) else None
            ) or None
            direct_hashes: dict[str, Any] = getattr(event, "hashes", {}) or {}
            direct_sha256: str | None = (
                direct_hashes.get("sha256") if isinstance(direct_hashes, dict) else None
            ) or None
            direct_iv_raw = getattr(event, "iv", None)
            direct_iv: str | None = direct_iv_raw if isinstance(direct_iv_raw, str) else None
            if direct_key and direct_sha256 and direct_iv:
                body = decrypt_attachment(body, direct_key, direct_sha256, direct_iv)
            else:
                logger.warning(
                    "MatrixChannel: missing E2EE key material on event attrs for event={}, "
                    "skipping decrypt",
                    event_id_val,
                )
        elif source_file:
            # Decrypt via BadEvent source path: key material lives in source["content"]["file"].
            from nio.crypto.attachments import decrypt_attachment  # noqa: PLC0415

            src_key_dict: dict[str, Any] = (
                source_file.get("key", {}) if isinstance(source_file.get("key"), dict) else {}
            )
            src_key: str | None = src_key_dict.get("k") or None
            src_hashes: dict[str, Any] = (
                source_file.get("hashes", {}) if isinstance(source_file.get("hashes"), dict) else {}
            )
            src_sha256: str | None = src_hashes.get("sha256") or None
            src_iv: str | None = source_file.get("iv") or None
            if src_key and src_sha256 and src_iv:
                body = decrypt_attachment(body, src_key, src_sha256, src_iv)
            else:
                logger.warning(
                    "MatrixChannel: missing E2EE key material in source for event={}, "
                    "skipping decrypt",
                    event_id_val,
                )

        raw_bytes = len(body)
        logger.debug(
            "MatrixChannel: downloaded mxc={} size={} mime={}", mxc, raw_bytes, declared_mime
        )

        # Post-fetch guard: discard if downloaded size exceeds download limit.
        if raw_bytes > max_download:
            logger.debug(
                "MatrixChannel: discard mxc={} size={} reason=exceeds_download_limit_postfetch",
                mxc,
                raw_bytes,
            )
            return f"[Anhang: {filename} — zu groß]", None

        # Determine MIME and extension.
        mimetype = declared_mime or getattr(resp, "content_type", "") or ""
        ext = mimetypes.guess_extension(mimetype) or ""

        # Save to temp file.
        sha = hashlib.sha256(body).hexdigest()[:8]
        tmp_path = Path(f"/tmp/squidbot-{sha}{ext}")
        await asyncio.to_thread(tmp_path.write_bytes, body)
        text = f"[Anhang: {filename} ({mimetype})] → {tmp_path}"

        # Decide whether to embed as multimodal content.
        multimodal_content: list[dict[str, Any]] | None = None
        if mimetype not in EMBEDDABLE_IMAGE_MIMES:
            logger.debug(
                "MatrixChannel: text_fallback mxc={} mime={} reason=non-image",
                mxc,
                mimetype,
            )
            logger.debug(
                "MatrixChannel: embed mxc={} embedded={} reason={}",
                mxc,
                False,
                "not_embedded",
            )
            return text, None

        # Encode-size estimate: 4 * ceil(raw / 3) + data-URL header length.
        estimated_encoded_bytes = 4 * ((raw_bytes + 2) // 3) + len(f"data:{mimetype};base64,")
        if estimated_encoded_bytes > max_embed:
            logger.debug(
                "MatrixChannel: text_fallback mxc={} mime={} encoded={} limit={} reason={}",
                mxc,
                mimetype,
                estimated_encoded_bytes,
                max_embed,
                "exceeds_embed_limit",
            )
            logger.debug(
                "MatrixChannel: embed mxc={} embedded={} reason={}",
                mxc,
                False,
                "size_exceeded",
            )
            return text, None

        # Build multimodal content: text description + image_url block.
        b64_data = base64.b64encode(body).decode("ascii")
        data_url = f"data:{mimetype};base64,{b64_data}"
        multimodal_content = [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        logger.debug("MatrixChannel: embedded mxc={} size={} mime={}", mxc, raw_bytes, mimetype)
        logger.debug(
            "MatrixChannel: embed mxc={} embedded={} reason={}",
            mxc,
            True,
            "embedded",
        )
        return text, multimodal_content

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
