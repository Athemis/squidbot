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

import re
from email.message import Message as EmailMessage
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
    if not addr:
        return ""
    addr = addr.strip()
    # Extract angle-bracket form: "Display Name <user@host>"
    match = re.search(r"<([^>]+)>", addr)
    if match:
        return match.group(1).strip().lower()
    return addr.lower()


class _Stripper(HTMLParser):
    """Minimal HTMLParser subclass that accumulates visible text."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:  # noqa: D102
        self._parts.append(data)

    def get_text(self) -> str:
        """Return concatenated text nodes."""
        return "".join(self._parts)


def _html_to_text(html_body: str) -> str:
    """
    Strip HTML tags and return plain text.

    Uses stdlib ``html.parser.HTMLParser`` — no third-party dependencies.

    Args:
        html_body: Raw HTML string.

    Returns:
        Plain-text representation with tags removed.
    """
    stripper = _Stripper()
    stripper.feed(html_body)
    return stripper.get_text()


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
        return "[Keine Textinhalte]"

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
        return "[Keine Textinhalte]"

    # multipart/signed — only examine Part 0 (the body; Part 1 is the sig)
    if subtype == "signed":
        if parts:
            return _extract_text(parts[0])
        return "[Keine Textinhalte]"

    # multipart/mixed and other containers — recurse into each part
    for part in parts:
        result = _extract_text(part)
        if result != "[Keine Textinhalte]":
            return result

    return "[Keine Textinhalte]"


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
    if re.match(r"re:\s", subject, re.IGNORECASE):
        return subject
    return f"Re: {subject}"
