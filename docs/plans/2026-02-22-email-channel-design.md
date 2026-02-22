# Email Channel Adapter — Design Document

**Date:** 2026-02-22
**Status:** Approved

## Motivation

squidbot needs an Email channel adapter so the bot can be reached via standard IMAP/SMTP
email. The adapter implements `ChannelPort` from `squidbot/core/ports.py` and lives entirely
in `squidbot/adapters/channels/email.py`. The core has no knowledge of email protocols.

## Scope

- Receiving messages via IMAP (IDLE with polling fallback)
- Sending replies via SMTP (Reply-To sender, thread headers preserved)
- Attachment handling: incoming saved to `/tmp/`, outgoing sent as MIME parts
- Markdown → HTML rendering for outgoing mail (multipart/alternative)
- `allow_from` filtering (allowlist of permitted sender addresses)
- TLS support: direct SSL (default for IMAP) and STARTTLS (default for SMTP)
- Log warnings when TLS is weakened or disabled

Out of scope: POP3, OAuth2, HTML-to-Markdown conversion for incoming mails, read receipts,
mail folder management beyond marking as `\Seen`.

## Architecture

```
AgentLoop
    │  InboundMessage / OutboundMessage
    ▼
EmailChannel  (adapters/channels/email.py)
    │  aioimaplib.IMAP4_SSL / IMAP4   (receive)
    │  aiosmtplib.SMTP                (send)
    ▼
Mail Server  (IMAP port 993 or 143, SMTP port 587 or 465)
```

`EmailChannel` implements `ChannelPort` structurally (no inheritance). `streaming = False` —
the full response is accumulated before sending. An internal asyncio Task drives the IMAP
loop; `receive()` yields from an `asyncio.Queue[InboundMessage]`.

## IMAP Loop

```
_connect_imap()

loop:
  try:
    fetch_unseen()       # SEARCH UNSEEN → FETCH RFC822 per UID → queue InboundMessages
                         # STORE +FLAGS (\Seen) after processing each message

    if _idle_supported:
      idle = await imap.idle_start(timeout=29*60)   # RFC2177: renew before 30min
      push = await imap.wait_server_push()
      imap.idle_done()
      await asyncio.wait_for(idle, 30)
      # STOP_WAIT_SERVER_PUSH → timeout expired, loop continues normally
    else:
      await asyncio.sleep(config.poll_interval_seconds)

  except <IDLE not supported>:
    _idle_supported = False    # permanent switch to polling for this session
  except <connection error>:
    await _reconnect_with_backoff()   # exponential: 1s, 2s, 4s, … cap 60s
```

**Duplicate prevention:** `_seen_uids: set[str]` tracks UIDs processed in this session.
On reconnect the `\Seen` flag on the server prevents re-processing.

**IDLE timeout:** aioimaplib's `timeout` parameter triggers an automatic `DONE` when
elapsed; `wait_server_push()` returns `STOP_WAIT_SERVER_PUSH`. The loop simply continues.

## Receiving Messages

### Parsing

Incoming messages are parsed with `email.message_from_bytes()` (stdlib).

**Session:**
```python
Session(channel="email", sender_id=normalized_from_address)
```
`sender_id` = lowercase `addr@domain` (display name stripped).

**Filtering:** If `allow_from` is non-empty, only senders in the list are processed.
Filtered mails are marked `\Seen` and silently dropped.

**Text extraction priority:**
1. `multipart/alternative` → prefer `text/plain` part
2. Only `text/plain` → use directly
3. Only `text/html` → strip tags with `html.parser` (stdlib)
4. No text part → `"[Keine Textinhalte]"`

**Incoming attachments:** All parts with `Content-Disposition: attachment` are saved to
`/tmp/squidbot-<sha256[:8]>.<ext>`. A line is appended to the message text:
```
[Anhang: filename.pdf (application/pdf)] → /tmp/squidbot-a1b2c3d4.pdf
```

### Metadata

```python
{
    "email_message_id":  "<abc@host>",     # Message-ID header
    "email_subject":     "Anfrage",        # Subject header (without Re: prefix)
    "email_from":        "user@example.com",
    "email_references":  "<prev@host>",    # References header (may be empty)
    "email_in_reply_to": "<prev@host>",    # In-Reply-To header (may be empty)
}
```

## Sending Messages

### MIME Structure

```
multipart/mixed            (only when OutboundMessage.attachment is set)
└── multipart/alternative
│   ├── text/plain         (OutboundMessage.text verbatim)
│   └── text/html          (rendered via markdown-it-py)
└── <attachment part>      (Content-Disposition: attachment)
```

If no attachment: `multipart/alternative` is the top-level part.

### Reply Headers

```
To:           <email_from>
Subject:      Re: <email_subject>   (no double "Re: Re:")
In-Reply-To:  <email_message_id>
References:   <email_references> <email_message_id>   (space-separated, old + new)
From:         <config.from_address>
```

### SMTP Connection

`aiosmtplib.SMTP` is connected per `send()` call and closed afterwards. No persistent
SMTP keepalive — email traffic is infrequent enough that per-call connect is fine.

STARTTLS is used by default (`smtp_starttls=True`, port 587). Direct SSL is available
via `smtp_starttls=False`, port 465.

**Error handling:** SMTP errors are logged at ERROR level; the channel loop continues.

## TLS Configuration

| Field | Default | Meaning |
|-------|---------|---------|
| `tls` | `True` | Enable TLS for both IMAP and SMTP. Set `False` only for local test servers. |
| `tls_verify` | `True` | Verify TLS certificates. Set `False` only for self-signed test certs. |
| `imap_starttls` | `False` | Use STARTTLS on IMAP (port 143). Default: direct SSL (port 993). |
| `smtp_starttls` | `True` | Use STARTTLS on SMTP (port 587). Set `False` for direct SSL (port 465). |

**aioimaplib connection selection:**

| `tls` | `imap_starttls` | Class used |
|-------|-----------------|-----------|
| `True` | `False` | `IMAP4_SSL(host, port, ssl_context=ctx)` |
| `True` | `True` | `IMAP4(host, port)` → `await imap.starttls(ctx)` |
| `False` | — | `IMAP4(host, port)` (plaintext) |

**Log warnings** (emitted once at startup):
```
tls=False        → WARNING "email: TLS disabled — connections are unencrypted (insecure)"
tls_verify=False → WARNING "email: TLS certificate verification disabled — insecure"
```

## Configuration (`EmailChannelConfig`)

```python
class EmailChannelConfig(BaseModel):
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
    tls: bool = True
    tls_verify: bool = True
    imap_starttls: bool = False
    smtp_starttls: bool = True
```

Changes from the existing stub: `use_tls` removed; `poll_interval_seconds`,
`imap_starttls`, `smtp_starttls` added; `smtp_port` default changed from 587 (unchanged)
to 587; `imap_port` default 993 unchanged.

## New Dependencies

| Package | Use | Optional? |
|---------|-----|-----------|
| `aioimaplib>=1.0` | IMAP IDLE, fetch, flag operations | No |
| `aiosmtplib>=3.0` | SMTP send | No |

`email`, `html.parser`, `mimetypes`, `hashlib` — all stdlib, no new dependencies.

## Testing Strategy

`tests/adapters/channels/test_email.py` uses `unittest.mock` to patch `aioimaplib` and
`aiosmtplib`. No real mail server needed.

Key test cases:
- `receive()` yields `InboundMessage` for unseen messages
- `allow_from` filter silently drops unknown senders (marks `\Seen`)
- Incoming attachment saved to `/tmp/`, path appended to text
- `send()` builds correct reply headers (In-Reply-To, References, Re: subject)
- `send()` produces `multipart/alternative` with plain + HTML parts
- `send()` wraps in `multipart/mixed` when `OutboundMessage.attachment` is set
- IDLE fallback switches to polling on unsupported servers
- Reconnect backoff: delays are 1s, 2s, 4s, …, capped at 60s
- TLS warnings logged when `tls=False` or `tls_verify=False`

## File Changes Summary

| File | Change |
|------|--------|
| `squidbot/adapters/channels/email.py` | New: `EmailChannel` |
| `squidbot/config/schema.py` | Update `EmailChannelConfig`: remove `use_tls`, add `poll_interval_seconds`, `imap_starttls`, `smtp_starttls`; change `smtp_port` default to 587 |
| `squidbot/cli/main.py` | Add email branch in `_run_gateway()` |
| `pyproject.toml` | Add `aioimaplib>=1.0`, `aiosmtplib>=3.0` |
| `tests/adapters/channels/test_email.py` | New: unit tests |
