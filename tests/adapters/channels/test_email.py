"""Tests for EmailChannel MIME parsing helpers."""

from __future__ import annotations

import email as email_lib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


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
