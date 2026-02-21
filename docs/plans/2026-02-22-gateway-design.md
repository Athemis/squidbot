# Gateway Mode Design

**Date:** 2026-02-22
**Status:** Approved

## Overview

`squidbot gateway` is extended to support two real external channels: **Matrix** (via
`matrix-nio`) and **Email** (via IMAP IDLE + SMTP). Both channels run as parallel async
tasks inside an `asyncio.TaskGroup`. Each channel adapter implements `ChannelPort` with
`streaming = False` — responses are accumulated fully before sending, enabling proper
Markdown/HTML rendering.

## Architecture

```
cli/main.py::_run_gateway()
    ├── MatrixChannelAdapter  (implements ChannelPort)
    │       ↕  matrix-nio AsyncClient (sync loop)
    └── EmailChannelAdapter   (implements ChannelPort)
            ↕  aioimaplib (IMAP IDLE) + aiosmtplib (SMTP)

Both adapters → SessionManager → AgentLoop (one per sender_id)
                                      ↓
                                 JsonlMemory (~/.squidbot/sessions/<channel>/<sender_id>/)
```

## Session Management

A `SessionManager` maintains a `dict[str, AgentLoop]` keyed on `sender_id`:

- **Matrix:** `@user:homeserver.tld`
- **Email:** `from@example.com` (normalized to lowercase)

On first message from a sender, a new `AgentLoop` is instantiated with its own
`JsonlMemory` stored at `~/.squidbot/sessions/<channel>/<sender_id>/memory.jsonl`.
On subsequent messages the existing instance is reused (history loaded from disk).

**Allowlist enforcement:** Each adapter checks `sender_id in config.allow_from` before
passing the message to the `SessionManager`. Unknown senders are silently dropped — no
error is leaked to them.

## Matrix Adapter (`adapters/channels/matrix.py`)

- Uses `matrix-nio`'s `AsyncClient` in a long-running sync loop.
- Listens for `RoomMessageText` events.
- Filters out messages sent by the bot itself (by `event.sender == client.user_id`).
- Before calling `AgentLoop.run()`, sends `m.typing` to the room.
- After `AgentLoop.run()` completes, sends `m.room.message` with:
  - `body`: plain text (Markdown source)
  - `formatted_body`: HTML rendered from Markdown (`markdown-it-py` or similar)
  - `format`: `org.matrix.custom.html`
- `streaming = False`
- Reconnects with exponential backoff (up to 5 attempts, then logs and exits).

### Config fields used

```python
MatrixChannelConfig:
    homeserver: str          # e.g. "https://matrix.org"
    user_id: str             # e.g. "@squidbot:matrix.org"
    access_token: str
    allow_from: list[str]    # e.g. ["@alice:matrix.org"]
    group_policy: str        # "allow" | "deny" (for group rooms)
```

## Email Adapter (`adapters/channels/email.py`)

- Uses `aioimaplib` with IMAP IDLE for push-based message delivery.
- Parses incoming messages with the stdlib `email` module (plaintext part only).
- Sends replies via `aiosmtplib` with proper threading headers:
  - `In-Reply-To: <original Message-ID>`
  - `References: <original Message-ID>`
  - `Subject: Re: <original subject>`
- `streaming = False`
- Reconnects with exponential backoff on IMAP/SMTP errors.

### Config fields used

```python
EmailChannelConfig:
    imap_host: str
    imap_port: int           # default 993
    imap_username: str
    imap_password: str
    smtp_host: str
    smtp_port: int           # default 587
    smtp_username: str
    smtp_password: str
    from_address: str        # e.g. "squidbot@example.com"
    allow_from: list[str]    # e.g. ["alice@example.com"]
```

## New Dependencies

| Package       | Purpose                  | Already present? |
|---------------|--------------------------|-----------------|
| `matrix-nio`  | Matrix client SDK        | Yes             |
| `aioimaplib`  | Async IMAP IDLE          | No — add        |
| `aiosmtplib`  | Async SMTP               | No — add        |

Markdown→HTML conversion for Matrix uses `markdown-it-py` (already used by Rich).

## Error Handling

| Scenario                        | Behavior                                       |
|---------------------------------|------------------------------------------------|
| Unknown sender                  | Silently drop — no response, no log noise      |
| IMAP/SMTP/Matrix disconnect     | Exponential backoff, max 5 retries, then exit  |
| Tool execution error            | `ToolResult(is_error=True, content=…)` as usual |
| LLM error                       | `_format_llm_error()` → sent as channel message |
| Malformed email (no text part)  | Log warning, skip message                      |

## Testing Strategy

- **`tests/adapters/channels/test_matrix.py`** — Mock `matrix-nio.AsyncClient`;
  verify allowlist filtering, session creation, typing event, room_send call.
- **`tests/adapters/channels/test_email.py`** — Mock `aioimaplib`/`aiosmtplib`;
  verify MIME parsing, plaintext extraction, reply header construction.
- **`tests/core/test_session_manager.py`** — Unit tests for `SessionManager`:
  session isolation per sender, session reuse, allowlist pass-through.
- All tests follow existing pattern: no network, no real FS (use `tmp_path`), no `asyncio.sleep`.
