"""
Email channel adapter for squidbot.

Implements ChannelPort using aioimaplib (IMAP IDLE with polling fallback) and
aiosmtplib (SMTP). Receives messages from a configured mailbox, filters by
allow_from, and sends replies as multipart/alternative (plain + HTML) emails.

Signature handling: multipart/signed emails are correctly unwrapped (text extracted
from Part 0). Signature type is stored in metadata. Cryptographic verification is
not implemented — see _verify_signature() stub for future extension.
"""

from __future__ import annotations

import asyncio
import email as email_lib
import hashlib
import mimetypes
import re
import ssl
from collections.abc import AsyncIterator
from email.message import Message as EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import aioimaplib
import aiosmtplib
import mistune
from loguru import logger

from squidbot.core.models import InboundMessage, OutboundMessage, Session

if TYPE_CHECKING:
    from squidbot.config.schema import EmailChannelConfig

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_NO_TEXT: str = "[Keine Textinhalte]"

_SKIP_TAGS: frozenset[str] = frozenset({"script", "style", "head"})

_md = mistune.create_markdown(escape=True)


def _normalize_address(addr: str) -> str:
    """
    Normalise an email address string to a bare, lowercase address.

    Strips any RFC 2822 display name (e.g. ``"Alice Smith <alice@example.com>"``
    becomes ``"alice@example.com"``) and lowercases the result.

    Args:
        addr: Raw address string, possibly including a display name.

    Returns:
        Bare lowercase email address, or an empty string if *addr* is empty.
    """
    _, address = parseaddr(addr)
    return address.strip("<> ").lower()


def _html_to_text(html_body: str) -> str:
    """Strip HTML tags and decode entities to produce plain text."""
    import html as _html_mod  # noqa: PLC0415
    import html.parser as _html_parser  # noqa: PLC0415

    class _Stripper(_html_parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self._parts: list[str] = []
            self._skip: int = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag.lower() in _SKIP_TAGS:
                self._skip += 1

        def handle_endtag(self, tag: str) -> None:
            if tag.lower() in _SKIP_TAGS and self._skip > 0:
                self._skip -= 1

        def handle_data(self, data: str) -> None:
            if self._skip == 0:
                self._parts.append(data)

        def get_text(self) -> str:
            return " ".join(self._parts).strip()

    stripper = _Stripper()
    stripper.feed(html_body)
    return _html_mod.unescape(stripper.get_text())


def _decode_part(part: EmailMessage) -> str:
    """
    Decode a single MIME part's payload to a Unicode string.

    Respects the part's declared charset; falls back to UTF-8, then Latin-1.

    Args:
        part: A leaf MIME part whose payload is bytes or str.

    Returns:
        Decoded text content of the part.
    """
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return str(payload or "")
    charset: str = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset)
    except UnicodeDecodeError, LookupError:
        return payload.decode("latin-1", errors="replace")


def _extract_text(msg: EmailMessage) -> str:
    """
    Extract the best available plain-text body from a MIME message.

    Priority order:
    1. ``text/plain`` parts (preferred over HTML).
    2. ``text/html`` parts (stripped of tags).
    3. Nested multipart containers are traversed recursively.

    For ``multipart/signed`` messages only Part 0 (the signed body) is
    inspected — the signature part is ignored.

    Args:
        msg: A parsed :class:`email.message.Message` object.

    Returns:
        Plain-text body, or ``"[Keine Textinhalte]"`` if none can be found.
    """
    # Leaf part — text/plain
    if msg.get_content_type() == "text/plain":
        return _decode_part(msg).strip()

    # Leaf part — text/html (strip tags)
    if msg.get_content_type() == "text/html":
        return _html_to_text(_decode_part(msg)).strip()

    # Non-multipart, non-text leaf (e.g. application/octet-stream)
    if not msg.is_multipart():
        return _NO_TEXT

    subtype = msg.get_content_subtype()  # "alternative", "signed", "mixed", …
    parts: list[EmailMessage] = msg.get_payload()  # type: ignore[assignment]

    # multipart/alternative — prefer plain over html
    if subtype == "alternative":
        plain_text: str | None = None
        html_text: str | None = None
        for part in parts:
            ct = part.get_content_type()
            if ct == "text/plain" and plain_text is None:
                plain_text = _decode_part(part).strip()
            elif ct == "text/html" and html_text is None:
                html_text = _html_to_text(_decode_part(part)).strip()
        if plain_text is not None:
            return plain_text
        if html_text is not None:
            return html_text
        return _NO_TEXT

    # multipart/signed — only examine Part 0 (the body; Part 1 is the sig)
    if subtype == "signed":
        if parts:
            return _extract_text(parts[0])
        return _NO_TEXT

    # multipart/mixed and other containers — recurse into each part
    for part in parts:
        result = _extract_text(part)
        if result != _NO_TEXT:
            return result

    return _NO_TEXT


def _detect_signature_type(msg: EmailMessage) -> str | None:
    """
    Detect whether the message carries a cryptographic signature.

    Inspects the top-level content type for the two common multipart signature
    subtypes: ``multipart/signed`` with an S/MIME or PGP protocol parameter.

    Args:
        msg: A parsed :class:`email.message.Message` object.

    Returns:
        ``"pgp"`` for PGP/MIME signatures, ``"smime"`` for S/MIME signatures,
        or ``None`` if no recognised signature structure is found.
    """
    if msg.get_content_maintype() != "multipart":
        return None
    if msg.get_content_subtype() != "signed":
        return None
    raw_protocol = msg.get_param("protocol")
    protocol: str = raw_protocol.lower() if isinstance(raw_protocol, str) else ""
    if "pgp" in protocol:
        return "pgp"
    if "pkcs7" in protocol or "smime" in protocol:
        return "smime"
    return None


def _re_subject(subject: str) -> str:
    """
    Prepend ``"Re: "`` to *subject* unless it already starts with a reply prefix.

    The check is case-insensitive so ``"RE: …"`` and ``"Re: …"`` are both
    treated as already-replied subjects.

    Args:
        subject: Original email subject line.

    Returns:
        Subject with exactly one ``"Re: "`` prefix.
    """
    if re.match(r"^re:\s*", subject, re.IGNORECASE):
        return subject
    return f"Re: {subject}"


def _extract_attachments(msg: EmailMessage, tmp_dir: Path) -> list[str]:
    """
    Extract all attachment parts and save them to tmp_dir.

    Returns a list of annotation lines to append to the message text, e.g.:
    ["[Anhang: report.pdf (application/pdf)] → /tmp/squidbot-a1b2c3d4.pdf"]

    Args:
        msg: Parsed email.message.Message object.
        tmp_dir: Directory to save attachments into.
    """
    lines: list[str] = []
    for part in msg.walk():
        disposition = part.get_content_disposition()
        if disposition != "attachment":
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        filename: str = part.get_filename() or "attachment"
        mime: str = part.get_content_type() or "application/octet-stream"
        ext = mimetypes.guess_extension(mime) or Path(filename).suffix or ""
        sha = hashlib.sha256(payload).hexdigest()[:8]
        dest = tmp_dir / f"squidbot-{sha}{ext}"
        dest.write_bytes(payload)
        lines.append(f"[Anhang: {filename} ({mime})] → {dest}")
    return lines


# ---------------------------------------------------------------------------
# Constants for EmailChannel
# ---------------------------------------------------------------------------

_TMP_DIR = Path("/tmp")
_IDLE_TIMEOUT_S: int = 29 * 60  # RFC2177: renew before server's 30min limit
_BACKOFF_CAP_S: float = 60.0


# ---------------------------------------------------------------------------
# EmailChannel
# ---------------------------------------------------------------------------


class EmailChannel:
    """
    Email channel adapter.

    Connects to an IMAP server, polls for new messages (IDLE preferred,
    polling fallback), and sends replies via SMTP.

    Args:
        config: EmailChannelConfig from squidbot settings.
        tmp_dir: Directory for saving incoming attachments (default: /tmp).
    """

    streaming: bool = False

    def __init__(
        self,
        config: EmailChannelConfig,
        tmp_dir: Path = _TMP_DIR,
    ) -> None:
        """Initialize EmailChannel with the given configuration."""
        self._config = config
        self._tmp_dir = tmp_dir
        self._queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._seen_uids: set[str] = set()
        self._idle_supported: bool = True
        self._imap: aioimaplib.IMAP4 | aioimaplib.IMAP4_SSL | None = None
        self._warn_tls()

    def _warn_tls(self) -> None:
        """Emit security warnings for weakened TLS settings."""
        if not self._config.tls:
            logger.warning("email: TLS disabled — connections are unencrypted (insecure)")
        elif not self._config.tls_verify:
            logger.warning("email: TLS certificate verification disabled — insecure")

    # ── ChannelPort interface ────────────────────────────────────────────────

    async def receive(self) -> AsyncIterator[InboundMessage]:
        """Yield inbound messages as they arrive from IMAP."""
        asyncio.create_task(self._imap_loop())
        while True:
            msg = await self._queue.get()
            yield msg

    async def send(self, message: OutboundMessage) -> None:
        """
        Send a reply email via SMTP.

        Builds a multipart/alternative message (plain + HTML rendered from Markdown).
        If message.attachment is set and exists, wraps in multipart/mixed.

        Args:
            message: Outbound message with text, optional attachment, and email metadata.
        """
        from email import encoders  # noqa: PLC0415
        from email.mime.base import MIMEBase  # noqa: PLC0415
        from email.mime.multipart import MIMEMultipart  # noqa: PLC0415
        from email.mime.text import MIMEText  # noqa: PLC0415

        meta = message.metadata
        to_addr: str = str(meta.get("email_from", message.session.sender_id))
        subject: str = _re_subject(str(meta.get("email_subject", "")))
        in_reply_to: str = str(meta.get("email_message_id", ""))
        old_refs: str = str(meta.get("email_references", ""))
        references: str = (old_refs + " " + in_reply_to).strip()

        # Build multipart/alternative (plain + HTML)
        plain_part = MIMEText(message.text, "plain", "utf-8")
        html_body = cast(str, _md(message.text))
        html_part = MIMEText(html_body, "html", "utf-8")
        alt = MIMEMultipart("alternative")
        alt.attach(plain_part)
        alt.attach(html_part)

        if message.attachment and message.attachment.exists():
            outer = MIMEMultipart("mixed")
            outer.attach(alt)
            att_data = message.attachment.read_bytes()
            att_mime, _ = mimetypes.guess_type(message.attachment.name)
            att_part = MIMEBase(*(att_mime or "application/octet-stream").split("/", 1))
            att_part.set_payload(att_data)
            encoders.encode_base64(att_part)
            att_part.add_header(
                "Content-Disposition",
                "attachment",
                filename=message.attachment.name,
            )
            outer.attach(att_part)
            root: MIMEMultipart = outer
        else:
            root = alt

        root["From"] = self._config.from_address
        root["To"] = to_addr
        root["Subject"] = subject
        if in_reply_to:
            root["In-Reply-To"] = in_reply_to
        if references:
            root["References"] = references

        cfg = self._config
        ssl_ctx: ssl.SSLContext | None = None
        if cfg.tls:
            ssl_ctx = ssl.create_default_context()
            if not cfg.tls_verify:
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

        try:
            smtp = aiosmtplib.SMTP(
                hostname=cfg.smtp_host,
                port=cfg.smtp_port,
                tls_context=ssl_ctx if not cfg.smtp_starttls else None,
                use_tls=cfg.tls and not cfg.smtp_starttls,
            )
            async with smtp:
                if cfg.tls and cfg.smtp_starttls:
                    await smtp.ehlo()
                    await smtp.starttls(tls_context=ssl_ctx)
                await smtp.login(cfg.username, cfg.password)
                await smtp.send_message(root)
                logger.info("email: reply sent to {}", to_addr)
        except Exception as exc:  # noqa: BLE001
            logger.error("email: SMTP error sending to {}: {}", to_addr, exc)

    async def send_typing(self, session_id: str) -> None:
        """No-op: email does not support typing indicators."""

    # ── IMAP loop ────────────────────────────────────────────────────────────

    async def _imap_loop(self) -> None:
        """Drive the IMAP connection: fetch unseen, then IDLE or poll."""
        backoff = 1.0
        while True:
            try:
                await self._connect_imap()
                backoff = 1.0  # reset on successful connect
                while True:
                    await self._fetch_unseen()
                    if self._idle_supported:
                        await self._idle_once()
                    else:
                        await asyncio.sleep(self._config.poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("email: IMAP error: {} — reconnecting in {}s", exc, backoff)
                self._imap = None
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_CAP_S)

    async def _connect_imap(self) -> None:
        """Establish IMAP connection, login, and select INBOX."""
        if self._imap is not None:
            return
        cfg = self._config
        ssl_ctx: ssl.SSLContext | None = None
        if cfg.tls:
            ssl_ctx = ssl.create_default_context()
            if not cfg.tls_verify:
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

        if not cfg.tls:
            imap: aioimaplib.IMAP4 | aioimaplib.IMAP4_SSL = aioimaplib.IMAP4(
                host=cfg.imap_host, port=cfg.imap_port
            )
        elif cfg.imap_starttls:
            imap = aioimaplib.IMAP4(host=cfg.imap_host, port=cfg.imap_port)
        else:
            imap = aioimaplib.IMAP4_SSL(host=cfg.imap_host, port=cfg.imap_port, ssl_context=ssl_ctx)

        await imap.wait_hello_from_server()

        if cfg.tls and cfg.imap_starttls and ssl_ctx is not None:
            await imap.starttls(ssl_ctx)

        await imap.login(cfg.username, cfg.password)
        await imap.select("INBOX")
        self._imap = imap
        logger.info("email: IMAP connected to {}", cfg.imap_host)

    async def _fetch_unseen(self) -> None:
        """Fetch all unseen messages and enqueue them as InboundMessages."""
        assert self._imap is not None
        status, data = await self._imap.uid("search", None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return
        uid_list = data[0].decode().split() if isinstance(data[0], bytes) else []
        for uid in uid_list:
            if uid in self._seen_uids:
                continue
            await self._fetch_and_enqueue(uid)

    async def _fetch_and_enqueue(self, uid: str) -> None:
        """Fetch a single message by UID, parse it, and enqueue."""
        assert self._imap is not None
        status, data = await self._imap.uid("fetch", uid, "(RFC822)")
        if status != "OK" or len(data) < 2:
            return
        raw = data[1] if isinstance(data[1], bytes) else None
        if raw is None:
            return

        msg = email_lib.message_from_bytes(raw)
        from_raw: str = msg.get("From") or ""
        sender = _normalize_address(from_raw)

        # allow_from filter
        if self._config.allow_from and sender not in self._config.allow_from:
            await self._imap.uid("store", uid, "+FLAGS", r"(\Seen)")
            self._seen_uids.add(uid)
            return

        text = _extract_text(msg)
        attachment_lines = _extract_attachments(msg, self._tmp_dir)
        if attachment_lines:
            text = text + "\n" + "\n".join(attachment_lines)

        subject: str = msg.get("Subject") or ""
        message_id: str = msg.get("Message-ID") or ""
        references: str = msg.get("References") or ""
        in_reply_to: str = msg.get("In-Reply-To") or ""
        sig_type = _detect_signature_type(msg)

        metadata: dict[str, Any] = {
            "email_message_id": message_id,
            "email_subject": subject,
            "email_from": sender,
            "email_references": references,
            "email_in_reply_to": in_reply_to,
            "email_signature_type": sig_type,
            "email_signature_valid": None,
            "email_signature_signer": None,
        }

        session = Session(channel="email", sender_id=sender)
        inbound = InboundMessage(session=session, text=text, metadata=metadata)
        self._seen_uids.add(uid)
        self._queue.put_nowait(inbound)

        await self._imap.uid("store", uid, "+FLAGS", r"(\Seen)")

    async def _idle_once(self) -> None:
        """Run one IDLE cycle. Switches to polling if IDLE is unsupported."""
        assert self._imap is not None
        try:
            idle = await self._imap.idle_start(timeout=_IDLE_TIMEOUT_S)
            await self._imap.wait_server_push()
            self._imap.idle_done()
            await asyncio.wait_for(idle, 30)
        except Exception as exc:  # noqa: BLE001
            err = str(exc).lower()
            if "idle" in err and ("not support" in err or "unknown" in err):
                logger.info("email: IMAP IDLE not supported, switching to polling")
                self._idle_supported = False
            else:
                raise

    def _verify_signature(self, msg: EmailMessage) -> None:
        """
        Stub for future S/MIME and GPG signature verification.

        When implemented, this method should:
        1. Detect signature type via _detect_signature_type()
        2. Verify via `cryptography` lib (S/MIME) or gpg subprocess (PGP)
        3. Check signer cert/key against a configured whitelist
        4. Set email_signature_valid and email_signature_signer in metadata

        Args:
            msg: Parsed email message. Not used yet.
        """
