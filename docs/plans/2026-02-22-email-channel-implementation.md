# Email Channel Adapter — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement `EmailChannel` — a `ChannelPort` adapter that receives mail via IMAP
(IDLE with polling fallback) and replies via SMTP, with TLS-by-default and extensible
signature handling.

**Architecture:** `EmailChannel` in `squidbot/adapters/channels/email.py` implements
`ChannelPort` structurally. An internal asyncio Task drives the IMAP loop and feeds an
`asyncio.Queue[InboundMessage]`. `send()` opens a fresh SMTP connection per call.
`streaming = False`.

**Tech Stack:** `aioimaplib>=1.0` (IMAP IDLE), `aiosmtplib>=3.0` (SMTP), stdlib `email`
(MIME parsing), `markdown-it-py` (already in deps, Markdown→HTML), `html.parser` (stdlib,
HTML→plaintext fallback).

**Design doc:** `docs/plans/2026-02-22-email-channel-design.md`

**Reference implementation:** `squidbot/adapters/channels/matrix.py` — follow the same
structural patterns (asyncio.Queue, streaming=False, metadata dict, `_connect` guard).

---

## Task 1: Dependencies + Config

**Files:**
- Modify: `pyproject.toml`
- Modify: `squidbot/config/schema.py`

**Step 1: Add dependencies to pyproject.toml**

In the `dependencies` list, add after `"markdown-it-py>=3.0"`:
```toml
"aioimaplib>=1.0",
"aiosmtplib>=3.0",
```

Also add mypy overrides at the bottom of `pyproject.toml` — in `[[tool.mypy.overrides]]`
extend the existing module list or add a new block:
```toml
[[tool.mypy.overrides]]
module = ["aioimaplib", "aioimaplib.*", "aiosmtplib", "aiosmtplib.*"]
ignore_missing_imports = true
```

**Step 2: Install new dependencies**

```bash
uv sync
```
Expected: resolves and installs `aioimaplib` and `aiosmtplib` without errors.

**Step 3: Update EmailChannelConfig in schema.py**

Replace the existing `EmailChannelConfig` class (lines 98–109) with:

```python
class EmailChannelConfig(BaseModel):
    """Configuration for the Email channel adapter."""

    enabled: bool = False
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    from_address: str = ""
    allow_from: list[str] = Field(default_factory=list)
    poll_interval_seconds: int = 60
    tls: bool = True          # False = plaintext (local test servers only)
    tls_verify: bool = True   # False = skip certificate verification
    imap_starttls: bool = False  # True = STARTTLS on port 143 instead of SSL on 993
    smtp_starttls: bool = True   # True = STARTTLS on port 587 (default); False = SSL on 465
```

**Step 4: Run ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```
Expected: no errors.

**Step 5: Commit**

```bash
git add pyproject.toml squidbot/config/schema.py
git commit --no-gpg-sign -m "deps: add aioimaplib and aiosmtplib; update EmailChannelConfig"
```

---

## Task 2: MIME Parsing Helpers (TDD)

These are pure functions — no I/O, easy to test first.

**Files:**
- Create: `squidbot/adapters/channels/email.py` (module + helpers only, no class yet)
- Create: `tests/adapters/channels/test_email.py`

**Step 1: Write failing tests for MIME helpers**

Create `tests/adapters/channels/test_email.py`:

```python
"""Tests for EmailChannel MIME parsing helpers."""

from __future__ import annotations

import email as email_lib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders


def _make_plain(body: str, from_addr: str = "sender@example.com") -> bytes:
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = from_addr
    msg["To"] = "bot@example.com"
    msg["Subject"] = "Test"
    msg["Message-ID"] = "<test123@example.com>"
    return msg.as_bytes()


def _make_html(body: str) -> bytes:
    msg = MIMEText(body, "html", "utf-8")
    msg["From"] = "sender@example.com"
    msg["To"] = "bot@example.com"
    msg["Subject"] = "Test"
    msg["Message-ID"] = "<test123@example.com>"
    return msg.as_bytes()


def _make_alternative(plain: str, html: str) -> bytes:
    msg = MIMEMultipart("alternative")
    msg["From"] = "sender@example.com"
    msg["To"] = "bot@example.com"
    msg["Subject"] = "Test"
    msg["Message-ID"] = "<test123@example.com>"
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg.as_bytes()


def _make_signed(plain: str) -> bytes:
    """Simulate a multipart/signed email."""
    msg = MIMEMultipart("signed", protocol="application/pgp-signature")
    msg["From"] = "sender@example.com"
    msg["To"] = "bot@example.com"
    msg["Subject"] = "Signed"
    msg["Message-ID"] = "<signed@example.com>"
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    sig = MIMEBase("application", "pgp-signature")
    sig.set_payload(b"fakesig")
    msg.attach(sig)
    return msg.as_bytes()


class TestExtractText:
    def test_plain_text_message(self) -> None:
        from squidbot.adapters.channels.email import _extract_text
        raw = _make_plain("Hello world")
        msg = email_lib.message_from_bytes(raw)
        assert _extract_text(msg) == "Hello world"

    def test_alternative_prefers_plain(self) -> None:
        from squidbot.adapters.channels.email import _extract_text
        raw = _make_alternative("plain text", "<p>html text</p>")
        msg = email_lib.message_from_bytes(raw)
        assert _extract_text(msg) == "plain text"

    def test_html_only_strips_tags(self) -> None:
        from squidbot.adapters.channels.email import _extract_text
        raw = _make_html("<p>Hello <b>world</b></p>")
        msg = email_lib.message_from_bytes(raw)
        result = _extract_text(msg)
        assert "Hello" in result
        assert "<p>" not in result

    def test_signed_mail_extracts_from_first_part(self) -> None:
        from squidbot.adapters.channels.email import _extract_text
        raw = _make_signed("Signed content")
        msg = email_lib.message_from_bytes(raw)
        assert _extract_text(msg) == "Signed content"

    def test_no_text_returns_placeholder(self) -> None:
        from squidbot.adapters.channels.email import _extract_text
        msg = MIMEBase("application", "octet-stream")
        msg.set_payload(b"binary")
        assert _extract_text(msg) == "[Keine Textinhalte]"


class TestNormalizeAddress:
    def test_plain_address(self) -> None:
        from squidbot.adapters.channels.email import _normalize_address
        assert _normalize_address("User@Example.COM") == "user@example.com"

    def test_display_name_stripped(self) -> None:
        from squidbot.adapters.channels.email import _normalize_address
        assert _normalize_address("Alice Smith <alice@example.com>") == "alice@example.com"

    def test_empty_returns_empty(self) -> None:
        from squidbot.adapters.channels.email import _normalize_address
        assert _normalize_address("") == ""


class TestDetectSignature:
    def test_pgp_signed(self) -> None:
        from squidbot.adapters.channels.email import _detect_signature_type
        raw = _make_signed("body")
        msg = email_lib.message_from_bytes(raw)
        assert _detect_signature_type(msg) == "pgp"

    def test_no_signature(self) -> None:
        from squidbot.adapters.channels.email import _detect_signature_type
        raw = _make_plain("body")
        msg = email_lib.message_from_bytes(raw)
        assert _detect_signature_type(msg) is None


class TestReSubject:
    def test_adds_re_prefix(self) -> None:
        from squidbot.adapters.channels.email import _re_subject
        assert _re_subject("Hello") == "Re: Hello"

    def test_no_double_re(self) -> None:
        from squidbot.adapters.channels.email import _re_subject
        assert _re_subject("Re: Hello") == "Re: Hello"

    def test_case_insensitive(self) -> None:
        from squidbot.adapters.channels.email import _re_subject
        assert _re_subject("RE: Hello") == "RE: Hello"
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/adapters/channels/test_email.py -v
```
Expected: `ModuleNotFoundError` or `ImportError` — `email.py` does not exist yet.

**Step 3: Create email.py with module docstring + helpers**

Create `squidbot/adapters/channels/email.py`:

```python
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

import email as email_lib
import hashlib
import html
import mimetypes
import re
from email.message import Message as EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Any


# ── MIME helpers ─────────────────────────────────────────────────────────────

def _normalize_address(addr: str) -> str:
    """
    Extract and normalize an email address.

    Strips display name and lowercases the result.

    Args:
        addr: Raw address string, e.g. "Alice <alice@example.com>" or "alice@example.com".

    Returns:
        Normalized lowercase address, e.g. "alice@example.com". Empty string if unparseable.
    """
    _, address = parseaddr(addr)
    return address.lower()


def _extract_text(msg: EmailMessage) -> str:
    """
    Extract plain text from an email message.

    Handles: text/plain, text/html (tags stripped), multipart/alternative
    (text/plain preferred), multipart/signed (unwraps to Part 0), and nested
    multiparts. Returns "[Keine Textinhalte]" if no text can be found.

    Args:
        msg: Parsed email.message.Message object.
    """
    content_type = msg.get_content_type()
    maintype = msg.get_content_maintype()

    # multipart/signed: real body is Part 0, Part 1 is the signature
    if content_type == "multipart/signed":
        parts = msg.get_payload()
        if isinstance(parts, list) and parts:
            return _extract_text(parts[0])  # type: ignore[arg-type]

    # multipart/alternative: prefer text/plain
    if content_type == "multipart/alternative":
        parts = msg.get_payload()
        if isinstance(parts, list):
            plain = next(
                (p for p in parts if p.get_content_type() == "text/plain"),  # type: ignore[union-attr]
                None,
            )
            if plain is not None:
                return _decode_part(plain)  # type: ignore[arg-type]
            # fallback: first part
            return _extract_text(parts[0])  # type: ignore[arg-type]

    # any other multipart: recurse into first text-bearing part
    if maintype == "multipart":
        parts = msg.get_payload()
        if isinstance(parts, list):
            for part in parts:
                result = _extract_text(part)  # type: ignore[arg-type]
                if result != "[Keine Textinhalte]":
                    return result
        return "[Keine Textinhalte]"

    # leaf parts
    if content_type == "text/plain":
        return _decode_part(msg)
    if content_type == "text/html":
        return _html_to_text(_decode_part(msg))

    return "[Keine Textinhalte]"


def _decode_part(part: EmailMessage) -> str:
    """Decode a leaf email part to a string."""
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace").strip()


def _html_to_text(html_body: str) -> str:
    """Strip HTML tags and unescape entities to produce plain text."""

    class _Stripper(html.parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self._parts: list[str] = []

        def handle_data(self, data: str) -> None:
            self._parts.append(data)

        def get_text(self) -> str:
            return " ".join(self._parts).strip()

    import html as html_module  # noqa: PLC0415

    stripper = _Stripper()
    stripper.feed(html_body)
    return html_module.unescape(stripper.get_text())


def _detect_signature_type(msg: EmailMessage) -> str | None:
    """
    Detect S/MIME or PGP signature presence.

    Returns "smime", "pgp", or None. Does not verify the signature.

    Args:
        msg: Parsed email.message.Message object.
    """
    content_type = msg.get_content_type()
    if content_type == "multipart/signed":
        protocol = msg.get_param("protocol", "") or ""
        if "pkcs7" in protocol or "x-pkcs7" in protocol:
            return "smime"
        if "pgp" in protocol:
            return "pgp"
        # check second part content type as fallback
        parts = msg.get_payload()
        if isinstance(parts, list) and len(parts) >= 2:
            sig_type = parts[1].get_content_type()  # type: ignore[union-attr]
            if "pkcs7" in sig_type or "x-pkcs7" in sig_type:
                return "smime"
            if "pgp" in sig_type:
                return "pgp"
    return None


def _re_subject(subject: str) -> str:
    """
    Prepend 'Re: ' to a subject line, avoiding double prefixes.

    Args:
        subject: Original subject string.

    Returns:
        Subject with exactly one 'Re: ' prefix.
    """
    if re.match(r"^re:", subject, re.IGNORECASE):
        return subject
    return f"Re: {subject}"
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/adapters/channels/test_email.py -v
```
Expected: all helper tests pass.

**Step 5: Run ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```
Expected: no errors.

**Step 6: Commit**

```bash
git add squidbot/adapters/channels/email.py tests/adapters/channels/test_email.py
git commit --no-gpg-sign -m "feat: add email channel MIME parsing helpers with tests"
```

---

## Task 3: Attachment Extraction Helper (TDD)

**Files:**
- Modify: `squidbot/adapters/channels/email.py`
- Modify: `tests/adapters/channels/test_email.py`

**Step 1: Write failing tests**

Add to `tests/adapters/channels/test_email.py`:

```python
class TestExtractAttachments:
    def test_no_attachments(self, tmp_path: Path) -> None:
        from squidbot.adapters.channels.email import _extract_attachments
        raw = _make_plain("body")
        msg = email_lib.message_from_bytes(raw)
        lines = _extract_attachments(msg, tmp_path)
        assert lines == []

    def test_attachment_saved_to_tmp(self, tmp_path: Path) -> None:
        from squidbot.adapters.channels.email import _extract_attachments
        outer = MIMEMultipart("mixed")
        outer["From"] = "s@example.com"
        outer["To"] = "b@example.com"
        outer["Subject"] = "With attachment"
        outer["Message-ID"] = "<att@example.com>"
        outer.attach(MIMEText("body", "plain"))
        part = MIMEBase("application", "pdf")
        part.set_payload(b"pdfcontent")
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="report.pdf")
        outer.attach(part)

        msg = email_lib.message_from_bytes(outer.as_bytes())
        lines = _extract_attachments(msg, tmp_path)
        assert len(lines) == 1
        assert "report.pdf" in lines[0]
        assert "application/pdf" in lines[0]
        # file actually exists
        saved = [f for f in tmp_path.iterdir()]
        assert len(saved) == 1
        assert saved[0].read_bytes() == b"pdfcontent"
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/adapters/channels/test_email.py::TestExtractAttachments -v
```
Expected: `ImportError` — `_extract_attachments` not defined yet.

**Step 3: Implement `_extract_attachments`**

Add to `squidbot/adapters/channels/email.py` after the existing helpers:

```python
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
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/adapters/channels/test_email.py -v
```
Expected: all tests pass.

**Step 5: Run ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```

**Step 6: Commit**

```bash
git add squidbot/adapters/channels/email.py tests/adapters/channels/test_email.py
git commit --no-gpg-sign -m "feat: add email attachment extraction helper with tests"
```

---

## Task 4: EmailChannel Class — receive() (TDD)

**Files:**
- Modify: `squidbot/adapters/channels/email.py`
- Modify: `tests/adapters/channels/test_email.py`

**Step 1: Write failing tests**

Add to `tests/adapters/channels/test_email.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from squidbot.config.schema import EmailChannelConfig


def _make_config(**kwargs: object) -> EmailChannelConfig:
    defaults: dict[str, object] = {
        "enabled": True,
        "imap_host": "imap.example.com",
        "smtp_host": "smtp.example.com",
        "username": "bot@example.com",
        "password": "secret",
        "from_address": "bot@example.com",
        "allow_from": [],
        "tls": False,       # avoid real SSL in tests
        "tls_verify": True,
    }
    defaults.update(kwargs)
    return EmailChannelConfig(**defaults)


class TestEmailChannelReceive:
    def _raw_mail(
        self,
        body: str = "Hello bot",
        from_addr: str = "user@example.com",
        subject: str = "Test",
        msg_id: str = "<abc@host>",
    ) -> bytes:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = from_addr
        msg["To"] = "bot@example.com"
        msg["Subject"] = subject
        msg["Message-ID"] = msg_id
        return msg.as_bytes()

    @pytest.fixture
    def fake_imap(self) -> MagicMock:
        imap = MagicMock()
        imap.wait_hello_from_server = AsyncMock()
        imap.login = AsyncMock(return_value=("OK", [b"Logged in"]))
        imap.select = AsyncMock(return_value=("OK", [b"1"]))
        imap.uid = AsyncMock()
        imap.idle_start = AsyncMock()
        imap.wait_server_push = AsyncMock(return_value="STOP_WAIT_SERVER_PUSH")
        imap.idle_done = MagicMock()
        imap.logout = AsyncMock()
        imap.has_pending_idle = MagicMock(return_value=False)
        return imap

    async def test_receive_yields_inbound_message(self, fake_imap: MagicMock, tmp_path: Path) -> None:
        from squidbot.adapters.channels.email import EmailChannel

        raw = self._raw_mail()
        # SEARCH UNSEEN returns one UID
        fake_imap.uid = AsyncMock(side_effect=[
            ("OK", [b"1"]),           # SEARCH UNSEEN → uid 1
            ("OK", [b"1", raw]),      # FETCH → raw bytes at index 1
            ("OK", [b"1"]),           # STORE +FLAGS \Seen
        ])

        config = _make_config()
        ch = EmailChannel(config=config, tmp_dir=tmp_path)

        with patch("squidbot.adapters.channels.email.aioimaplib.IMAP4", return_value=fake_imap):
            msgs: list[object] = []
            async for msg in ch.receive():
                msgs.append(msg)
                break

        assert len(msgs) == 1
        assert msgs[0].text == "Hello bot"  # type: ignore[union-attr]
        assert msgs[0].session.sender_id == "user@example.com"  # type: ignore[union-attr]

    async def test_allow_from_drops_unknown_sender(self, fake_imap: MagicMock, tmp_path: Path) -> None:
        from squidbot.adapters.channels.email import EmailChannel

        raw = self._raw_mail(from_addr="stranger@evil.com")
        fake_imap.uid = AsyncMock(side_effect=[
            ("OK", [b"1"]),
            ("OK", [b"1", raw]),
            ("OK", [b"1"]),   # STORE \Seen still called
            ("OK", []),        # second SEARCH: no new mail
        ])
        fake_imap.wait_server_push = AsyncMock(return_value="STOP_WAIT_SERVER_PUSH")

        config = _make_config(allow_from=["trusted@example.com"])
        ch = EmailChannel(config=config, tmp_dir=tmp_path)

        with patch("squidbot.adapters.channels.email.aioimaplib.IMAP4", return_value=fake_imap):
            received: list[object] = []
            async def _collect() -> None:
                async for msg in ch.receive():
                    received.append(msg)
            task = asyncio.create_task(_collect())
            await asyncio.sleep(0.05)
            task.cancel()

        assert received == []

    async def test_metadata_contains_email_fields(self, fake_imap: MagicMock, tmp_path: Path) -> None:
        from squidbot.adapters.channels.email import EmailChannel

        raw = self._raw_mail(subject="Anfrage", msg_id="<xyz@host>")
        fake_imap.uid = AsyncMock(side_effect=[
            ("OK", [b"1"]),
            ("OK", [b"1", raw]),
            ("OK", [b"1"]),
        ])

        config = _make_config()
        ch = EmailChannel(config=config, tmp_dir=tmp_path)

        with patch("squidbot.adapters.channels.email.aioimaplib.IMAP4", return_value=fake_imap):
            async for msg in ch.receive():
                assert msg.metadata["email_subject"] == "Anfrage"
                assert msg.metadata["email_message_id"] == "<xyz@host>"
                assert msg.metadata["email_from"] == "user@example.com"
                assert msg.metadata["email_signature_type"] is None
                break
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/adapters/channels/test_email.py::TestEmailChannelReceive -v
```
Expected: `ImportError` — `EmailChannel` not defined yet.

**Step 3: Implement EmailChannel.__init__ + receive() + IMAP loop**

Add to `squidbot/adapters/channels/email.py`:

```python
import asyncio
import ssl
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import aioimaplib
from loguru import logger

from squidbot.core.models import InboundMessage, OutboundMessage, Session

if TYPE_CHECKING:
    from squidbot.config.schema import EmailChannelConfig

_TMP_DIR = Path("/tmp")
_IDLE_TIMEOUT_S: int = 29 * 60   # RFC2177: renew before server's 30min limit
_BACKOFF_CAP_S: float = 60.0


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
        """Send a reply email via SMTP."""
        # implemented in Task 5
        pass

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
            imap = aioimaplib.IMAP4_SSL(
                host=cfg.imap_host, port=cfg.imap_port, ssl_context=ssl_ctx
            )

        await imap.wait_hello_from_server()

        if cfg.tls and cfg.imap_starttls and ssl_ctx is not None:
            await imap.starttls(ssl_ctx)  # type: ignore[union-attr]

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
        self._queue.put_nowait(inbound)
        self._seen_uids.add(uid)

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
```

**Step 4: Run tests**

```bash
uv run pytest tests/adapters/channels/test_email.py -v
```
Expected: all tests pass.

**Step 5: Run ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```

**Step 6: Commit**

```bash
git add squidbot/adapters/channels/email.py tests/adapters/channels/test_email.py
git commit --no-gpg-sign -m "feat: implement EmailChannel.receive() with IMAP IDLE loop"
```

---

## Task 5: EmailChannel.send() (TDD)

**Files:**
- Modify: `squidbot/adapters/channels/email.py`
- Modify: `tests/adapters/channels/test_email.py`

**Step 1: Write failing tests**

Add to `tests/adapters/channels/test_email.py`:

```python
class TestEmailChannelSend:
    def _make_outbound(
        self,
        text: str = "Response text",
        attachment: Path | None = None,
        subject: str = "Test",
        msg_id: str = "<abc@host>",
        references: str = "",
        to_addr: str = "user@example.com",
    ) -> object:
        from squidbot.core.models import OutboundMessage, Session
        session = Session(channel="email", sender_id=to_addr)
        return OutboundMessage(
            session=session,
            text=text,
            attachment=attachment,
            metadata={
                "email_from": to_addr,
                "email_subject": subject,
                "email_message_id": msg_id,
                "email_references": references,
            },
        )

    @pytest.fixture
    def fake_smtp(self) -> MagicMock:
        smtp = MagicMock()
        smtp.__aenter__ = AsyncMock(return_value=smtp)
        smtp.__aexit__ = AsyncMock(return_value=False)
        smtp.ehlo = AsyncMock()
        smtp.starttls = AsyncMock()
        smtp.login = AsyncMock()
        smtp.send_message = AsyncMock()
        return smtp

    async def test_send_reply_headers(self, fake_smtp: MagicMock, tmp_path: Path) -> None:
        from squidbot.adapters.channels.email import EmailChannel

        config = _make_config()
        ch = EmailChannel(config=config, tmp_dir=tmp_path)
        outbound = self._make_outbound()

        with patch("squidbot.adapters.channels.email.aiosmtplib.SMTP", return_value=fake_smtp):
            await ch.send(outbound)  # type: ignore[arg-type]

        fake_smtp.send_message.assert_called_once()
        sent = fake_smtp.send_message.call_args[0][0]
        assert sent["To"] == "user@example.com"
        assert sent["In-Reply-To"] == "<abc@host>"
        assert sent["Subject"] == "Re: Test"
        assert sent["From"] == "bot@example.com"

    async def test_send_multipart_alternative(self, fake_smtp: MagicMock, tmp_path: Path) -> None:
        from squidbot.adapters.channels.email import EmailChannel

        config = _make_config()
        ch = EmailChannel(config=config, tmp_dir=tmp_path)
        outbound = self._make_outbound(text="**bold**")

        with patch("squidbot.adapters.channels.email.aiosmtplib.SMTP", return_value=fake_smtp):
            await ch.send(outbound)  # type: ignore[arg-type]

        sent = fake_smtp.send_message.call_args[0][0]
        content_type = sent.get_content_type()
        assert content_type == "multipart/alternative"
        parts = sent.get_payload()
        assert isinstance(parts, list)
        types = [p.get_content_type() for p in parts]
        assert "text/plain" in types
        assert "text/html" in types

    async def test_send_with_attachment(self, fake_smtp: MagicMock, tmp_path: Path) -> None:
        from squidbot.adapters.channels.email import EmailChannel

        att = tmp_path / "report.pdf"
        att.write_bytes(b"pdfdata")
        config = _make_config()
        ch = EmailChannel(config=config, tmp_dir=tmp_path)
        outbound = self._make_outbound(attachment=att)

        with patch("squidbot.adapters.channels.email.aiosmtplib.SMTP", return_value=fake_smtp):
            await ch.send(outbound)  # type: ignore[arg-type]

        sent = fake_smtp.send_message.call_args[0][0]
        assert sent.get_content_type() == "multipart/mixed"
        parts = sent.get_payload()
        assert isinstance(parts, list)
        assert len(parts) == 2   # multipart/alternative + attachment

    async def test_send_references_header(self, fake_smtp: MagicMock, tmp_path: Path) -> None:
        from squidbot.adapters.channels.email import EmailChannel

        config = _make_config()
        ch = EmailChannel(config=config, tmp_dir=tmp_path)
        outbound = self._make_outbound(references="<prev@host>", msg_id="<cur@host>")

        with patch("squidbot.adapters.channels.email.aiosmtplib.SMTP", return_value=fake_smtp):
            await ch.send(outbound)  # type: ignore[arg-type]

        sent = fake_smtp.send_message.call_args[0][0]
        refs = sent["References"]
        assert "<prev@host>" in refs
        assert "<cur@host>" in refs
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/adapters/channels/test_email.py::TestEmailChannelSend -v
```
Expected: failures — `send()` is a stub.

**Step 3: Implement send()**

Replace the `send()` stub in `email.py` with:

```python
async def send(self, message: OutboundMessage) -> None:
    """Send a reply email via SMTP."""
    import aiosmtplib  # noqa: PLC0415
    from email.mime.base import MIMEBase  # noqa: PLC0415
    from email.mime.multipart import MIMEMultipart  # noqa: PLC0415
    from email.mime.text import MIMEText  # noqa: PLC0415
    from email import encoders  # noqa: PLC0415
    from markdown_it import MarkdownIt  # noqa: PLC0415

    meta = message.metadata
    to_addr: str = str(meta.get("email_from", message.session.sender_id))
    subject: str = _re_subject(str(meta.get("email_subject", "")))
    in_reply_to: str = str(meta.get("email_message_id", ""))
    old_refs: str = str(meta.get("email_references", ""))
    references: str = (old_refs + " " + in_reply_to).strip()

    # Build multipart/alternative
    plain_part = MIMEText(message.text, "plain", "utf-8")
    html_body = MarkdownIt().render(message.text)
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
            "Content-Disposition", "attachment",
            filename=message.attachment.name
        )
        outer.attach(att_part)
        root = outer
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
```

Also add at the top of the file with other imports:
```python
import aiosmtplib
```

**Step 4: Run tests**

```bash
uv run pytest tests/adapters/channels/test_email.py -v
```
Expected: all tests pass.

**Step 5: Run ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```

**Step 6: Commit**

```bash
git add squidbot/adapters/channels/email.py tests/adapters/channels/test_email.py
git commit --no-gpg-sign -m "feat: implement EmailChannel.send() with SMTP and multipart/alternative"
```

---

## Task 6: TLS Warning Tests + Gateway Wiring

**Files:**
- Modify: `tests/adapters/channels/test_email.py`
- Modify: `squidbot/cli/main.py`

**Step 1: Write TLS warning tests**

Add to `tests/adapters/channels/test_email.py`:

```python
class TestEmailChannelTlsWarnings:
    def test_warns_when_tls_disabled(self, caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
        import logging
        from squidbot.adapters.channels.email import EmailChannel
        config = _make_config(tls=False)
        with caplog.at_level(logging.WARNING):
            EmailChannel(config=config, tmp_dir=tmp_path)
        assert any("TLS disabled" in r.message for r in caplog.records)

    def test_warns_when_tls_verify_disabled(self, caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
        import logging
        from squidbot.adapters.channels.email import EmailChannel
        config = _make_config(tls=True, tls_verify=False)
        with caplog.at_level(logging.WARNING):
            EmailChannel(config=config, tmp_dir=tmp_path)
        assert any("certificate verification disabled" in r.message for r in caplog.records)

    def test_no_warning_for_default_tls(self, caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
        import logging
        from squidbot.adapters.channels.email import EmailChannel
        config = _make_config(tls=True, tls_verify=True)
        with caplog.at_level(logging.WARNING):
            EmailChannel(config=config, tmp_dir=tmp_path)
        assert not any("TLS" in r.message for r in caplog.records)
```

Note: loguru doesn't integrate with `caplog` by default. Use this pattern in the test
to capture loguru output:

```python
import logging
from loguru import logger

# Add this fixture at the top of the test class or as a module-level fixture:
@pytest.fixture(autouse=True)
def propagate_loguru(caplog: pytest.LogCaptureFixture) -> None:
    """Bridge loguru → stdlib logging so caplog can capture it."""
    handler_id = logger.add(
        lambda msg: logging.getLogger("loguru").warning(msg),
        level="WARNING",
        format="{message}",
    )
    yield
    logger.remove(handler_id)
```

Actually, the simpler approach for loguru is to patch `logger.warning` directly:

```python
def test_warns_when_tls_disabled(self, tmp_path: Path) -> None:
    from squidbot.adapters.channels.email import EmailChannel
    config = _make_config(tls=False)
    with patch("squidbot.adapters.channels.email.logger") as mock_logger:
        EmailChannel(config=config, tmp_dir=tmp_path)
    mock_logger.warning.assert_called_once()
    assert "TLS disabled" in mock_logger.warning.call_args[0][0]
```

Use the `patch("squidbot.adapters.channels.email.logger")` approach for all three tests.

**Step 2: Run to verify failure**

```bash
uv run pytest tests/adapters/channels/test_email.py::TestEmailChannelTlsWarnings -v
```
Expected: failures — logger mock isn't patched yet in implementation (but tests should run).

**Step 3: Wire EmailChannel into gateway**

In `squidbot/cli/main.py`, find the `_run_gateway()` function. After the matrix block
(around line 462), add the email channel branch inside the `async with asyncio.TaskGroup()` block:

```python
if settings.channels.email.enabled:
    from squidbot.adapters.channels.email import EmailChannel  # noqa: PLC0415

    email_ch = EmailChannel(config=settings.channels.email)
    channel_registry["email"] = email_ch
    logger.info("email channel: starting")
    tg.create_task(_channel_loop(email_ch, agent_loop))
else:
    logger.info("email channel: disabled")
```

**Step 4: Run all tests**

```bash
uv run pytest -q
```
Expected: all existing tests still pass, new TLS tests pass.

**Step 5: Run ruff + mypy**

```bash
uv run ruff check . && uv run mypy squidbot/
```

**Step 6: Commit**

```bash
git add squidbot/adapters/channels/email.py tests/adapters/channels/test_email.py squidbot/cli/main.py
git commit --no-gpg-sign -m "feat: wire EmailChannel into gateway; add TLS warning tests"
```

---

## Task 7: Final Verification

**Step 1: Full test suite**

```bash
uv run pytest -q
```
Expected: all tests pass (prior count was 166; new tests add ~20 more).

**Step 2: Lint + types**

```bash
uv run ruff check . && uv run mypy squidbot/
```
Expected: 0 errors.

**Step 3: Reinstall CLI**

```bash
uv tool install --reinstall /home/alex/git/squidbot
```

**Step 4: Smoke test status command**

```bash
squidbot status
```
Expected output includes `Email: disabled` (default config).

**Step 5: Final commit if any fixups needed**

```bash
git add -A && git commit --no-gpg-sign -m "chore: email channel final cleanup"
```
Only if there are outstanding changes. Otherwise skip.
