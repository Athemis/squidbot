"""Tests for EmailChannel MIME parsing helpers."""

from __future__ import annotations

import asyncio
import contextlib
import email as email_lib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
        "tls": False,  # avoid real SSL in tests
        "tls_verify": True,
    }
    defaults.update(kwargs)
    return EmailChannelConfig(**defaults)


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

    def test_html_strips_style_tag_content(self) -> None:
        from squidbot.adapters.channels.email import _extract_text

        raw = _make_html("<style>body { color: red; }</style><p>Hello</p>")
        msg = email_lib.message_from_bytes(raw)
        result = _extract_text(msg)
        assert "Hello" in result
        assert "color" not in result
        assert "red" not in result


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
        # filename follows squidbot-<sha8>.ext pattern
        assert saved[0].name.startswith("squidbot-")
        assert saved[0].name.endswith(".pdf")
        # annotation line ends with the saved path
        assert lines[0].endswith(str(saved[0]))


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

    async def test_receive_yields_inbound_message(
        self, fake_imap: MagicMock, tmp_path: Path
    ) -> None:
        from squidbot.adapters.channels.email import EmailChannel

        raw = self._raw_mail()
        # SEARCH UNSEEN → uid 1; FETCH → raw bytes at index 1; STORE +FLAGS \Seen
        fake_imap.uid = AsyncMock(
            side_effect=[
                ("OK", [b"1"]),
                ("OK", [b"1", raw]),
                ("OK", [b"1"]),
            ]
        )

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

    async def test_allow_from_drops_unknown_sender(
        self, fake_imap: MagicMock, tmp_path: Path
    ) -> None:
        from squidbot.adapters.channels.email import EmailChannel

        raw = self._raw_mail(from_addr="stranger@evil.com")
        fake_imap.uid = AsyncMock(
            side_effect=[
                ("OK", [b"1"]),
                ("OK", [b"1", raw]),
                ("OK", [b"1"]),  # STORE \Seen still called
                ("OK", []),  # second SEARCH: no new mail
            ]
        )
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
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert received == []

    async def test_metadata_contains_email_fields(
        self, fake_imap: MagicMock, tmp_path: Path
    ) -> None:
        from squidbot.adapters.channels.email import EmailChannel

        raw = self._raw_mail(subject="Anfrage", msg_id="<xyz@host>")
        fake_imap.uid = AsyncMock(
            side_effect=[
                ("OK", [b"1"]),
                ("OK", [b"1", raw]),
                ("OK", [b"1"]),
            ]
        )

        config = _make_config()
        ch = EmailChannel(config=config, tmp_dir=tmp_path)

        with patch("squidbot.adapters.channels.email.aioimaplib.IMAP4", return_value=fake_imap):
            async for msg in ch.receive():
                assert msg.metadata["email_subject"] == "Anfrage"
                assert msg.metadata["email_message_id"] == "<xyz@host>"
                assert msg.metadata["email_from"] == "user@example.com"
                assert msg.metadata["email_signature_type"] is None
                assert msg.metadata["email_signature_valid"] is None
                assert msg.metadata["email_signature_signer"] is None
                break
