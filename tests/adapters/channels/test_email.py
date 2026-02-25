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
    async def test_no_attachments(self, tmp_path: Path) -> None:
        from squidbot.adapters.channels.email import _extract_attachments

        raw = _make_plain("body")
        msg = email_lib.message_from_bytes(raw)
        lines = await _extract_attachments(msg, tmp_path)
        assert lines == []

    async def test_attachment_saved_to_tmp(self, tmp_path: Path) -> None:
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
        to_thread_calls: list[str] = []

        async def fake_to_thread(func: object, *args: object, **kwargs: object) -> object:
            method = func
            method_name = getattr(method, "__name__", repr(method))
            to_thread_calls.append(method_name)
            return method(*args, **kwargs)  # type: ignore[misc]

        with patch(
            "squidbot.adapters.channels.email.asyncio.to_thread",
            new=AsyncMock(side_effect=fake_to_thread),
        ):
            lines = await _extract_attachments(msg, tmp_path)

        assert len(lines) == 1
        assert "report.pdf" in lines[0]
        assert "application/pdf" in lines[0]
        assert "write_bytes" in to_thread_calls
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
        references: str = "",
        in_reply_to: str = "",
    ) -> bytes:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = from_addr
        msg["To"] = "bot@example.com"
        msg["Subject"] = subject
        msg["Message-ID"] = msg_id
        if references:
            msg["References"] = references
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
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

        raw = self._raw_mail(
            subject="Anfrage",
            msg_id="<xyz@host>",
            references="<prev@host>",
            in_reply_to="<prev@host>",
        )
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
                assert msg.metadata["email_references"] == "<prev@host>"
                assert msg.metadata["email_in_reply_to"] == "<prev@host>"
                assert msg.metadata["email_signature_type"] is None
                assert msg.metadata["email_signature_valid"] is None
                assert msg.metadata["email_signature_signer"] is None
                break


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

        to_thread_calls: list[str] = []

        async def fake_to_thread(func: object, *args: object, **kwargs: object) -> object:
            method = func
            method_name = getattr(method, "__name__", repr(method))
            to_thread_calls.append(method_name)
            return method(*args, **kwargs)  # type: ignore[misc]

        with (
            patch("squidbot.adapters.channels.email.aiosmtplib.SMTP", return_value=fake_smtp),
            patch(
                "squidbot.adapters.channels.email.asyncio.to_thread",
                new=AsyncMock(side_effect=fake_to_thread),
            ),
        ):
            await ch.send(outbound)  # type: ignore[arg-type]

        sent = fake_smtp.send_message.call_args[0][0]
        assert sent.get_content_type() == "multipart/mixed"
        parts = sent.get_payload()
        assert isinstance(parts, list)
        assert len(parts) == 2  # multipart/alternative + attachment
        assert "read_bytes" in to_thread_calls

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


class TestEmailChannelTlsWarnings:
    def test_warns_when_tls_disabled(self, tmp_path: Path) -> None:
        from squidbot.adapters.channels.email import EmailChannel

        config = _make_config(tls=False)
        with patch("squidbot.adapters.channels.email.logger") as mock_logger:
            EmailChannel(config=config, tmp_dir=tmp_path)
        mock_logger.warning.assert_called_once()
        assert "TLS disabled" in mock_logger.warning.call_args[0][0]

    def test_warns_when_tls_verify_disabled(self, tmp_path: Path) -> None:
        from squidbot.adapters.channels.email import EmailChannel

        config = _make_config(tls=True, tls_verify=False)
        with patch("squidbot.adapters.channels.email.logger") as mock_logger:
            EmailChannel(config=config, tmp_dir=tmp_path)
        mock_logger.warning.assert_called_once()
        assert "certificate verification disabled" in mock_logger.warning.call_args[0][0]

    def test_no_warning_for_default_tls(self, tmp_path: Path) -> None:
        from squidbot.adapters.channels.email import EmailChannel

        config = _make_config(tls=True, tls_verify=True)
        with patch("squidbot.adapters.channels.email.logger") as mock_logger:
            EmailChannel(config=config, tmp_dir=tmp_path)
        mock_logger.warning.assert_not_called()


class TestEmailChannelIdleFallback:
    async def test_idle_unsupported_sets_flag(self, tmp_path: Path) -> None:
        """_idle_once() sets _idle_supported=False when server reports IDLE not supported."""
        from squidbot.adapters.channels.email import EmailChannel

        config = _make_config()
        ch = EmailChannel(config=config, tmp_dir=tmp_path)

        fake_imap = MagicMock()
        fake_imap.idle_start = AsyncMock(side_effect=Exception("IDLE not supported by server"))
        ch._imap = fake_imap  # type: ignore[assignment]

        assert ch._idle_supported is True
        await ch._idle_once()
        assert ch._idle_supported is False

    async def test_idle_other_error_propagates(self, tmp_path: Path) -> None:
        """_idle_once() re-raises exceptions not related to IDLE support."""
        from squidbot.adapters.channels.email import EmailChannel

        config = _make_config()
        ch = EmailChannel(config=config, tmp_dir=tmp_path)

        fake_imap = MagicMock()
        fake_imap.idle_start = AsyncMock(side_effect=OSError("connection reset"))
        ch._imap = fake_imap  # type: ignore[assignment]

        with pytest.raises(OSError, match="connection reset"):
            await ch._idle_once()
        assert ch._idle_supported is True  # flag unchanged


class TestEmailChannelReconnectBackoff:
    async def test_backoff_doubles_on_each_failure(self, tmp_path: Path) -> None:
        """_imap_loop() sleeps 1s, 2s, 4s on consecutive connection failures."""
        from squidbot.adapters.channels.email import EmailChannel

        config = _make_config()
        ch = EmailChannel(config=config, tmp_dir=tmp_path)

        call_count = 0
        sleep_calls: list[float] = []

        async def fake_connect() -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise OSError("connection refused")
            # 4th call: cancel to stop the loop
            raise asyncio.CancelledError

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        with (
            patch.object(ch, "_connect_imap", side_effect=fake_connect),
            patch("squidbot.adapters.channels.email.asyncio.sleep", side_effect=fake_sleep),
            pytest.raises(asyncio.CancelledError),
        ):
            await ch._imap_loop()

        assert sleep_calls == [1.0, 2.0, 4.0]

    async def test_backoff_resets_after_successful_connect(self, tmp_path: Path) -> None:
        """_imap_loop() resets backoff to 1s after a successful connection."""
        from squidbot.adapters.channels.email import EmailChannel

        config = _make_config()
        ch = EmailChannel(config=config, tmp_dir=tmp_path)

        connect_count = 0
        sleep_calls: list[float] = []

        async def fake_connect() -> None:
            nonlocal connect_count
            connect_count += 1
            # 1st connect succeeds (backoff should reset)
            # but _fetch_unseen will fail, causing reconnect with fresh backoff

        fetch_count = 0

        async def fake_fetch() -> None:
            nonlocal fetch_count
            fetch_count += 1
            if fetch_count == 1:
                raise OSError("timeout")  # triggers backoff sleep of 1.0
            raise asyncio.CancelledError  # stop the loop on 2nd attempt

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        with (
            patch.object(ch, "_connect_imap", side_effect=fake_connect),
            patch.object(ch, "_fetch_unseen", side_effect=fake_fetch),
            patch("squidbot.adapters.channels.email.asyncio.sleep", side_effect=fake_sleep),
            pytest.raises(asyncio.CancelledError),
        ):
            await ch._imap_loop()

        # After first successful connect + fetch failure, backoff starts at 1.0 again
        assert sleep_calls == [1.0]
