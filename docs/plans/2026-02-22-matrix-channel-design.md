# Matrix Channel Adapter — Design Document

**Date:** 2026-02-22
**Status:** Approved
**Spec:** Matrix Client-Server API v1.17

## Motivation

squidbot needs a Matrix channel adapter so the bot can be used from any Matrix client
(Element, Cinny, etc.). The adapter must implement `ChannelPort` from `squidbot/core/ports.py`
and live entirely in `squidbot/adapters/channels/matrix.py`. The core must not need to know
anything about Matrix.

## Scope

- Receiving messages from Matrix rooms (filtered by `group_policy`)
- Sending text responses (with Markdown→HTML rendering)
- Typing notifications with spec-compliant keepalive loop
- Outgoing file attachments (`OutboundMessage.attachment`)
- Incoming file attachments (auto-download to `/tmp/`, path in message text)
- Thread context: bot replies in the same Matrix thread as the incoming message
- Reactions (incoming → `InboundMessage`; outgoing → via `OutboundMessage.metadata`)
- E2EE: transparent via matrix-nio's built-in crypto (no extra code required)

Out of scope: presence, read receipts, room creation, device verification UI.

## Architecture

`MatrixChannel` implements `ChannelPort` structurally (no inheritance).

```
AgentLoop
    │  InboundMessage / OutboundMessage
    ▼
MatrixChannel  (adapters/channels/matrix.py)
    │  matrix-nio AsyncClient
    ▼
Matrix Homeserver  (HTTPS)
```

`MatrixChannel` runs an internal `sync_forever()` loop and feeds incoming events into an
`asyncio.Queue[InboundMessage]`. `receive()` yields from that queue. `send()` accumulates
the full text (streaming=False) and posts it as a single Matrix event.

## Core Model Changes

`squidbot/core/models.py` gets two new fields:

```python
@dataclass
class InboundMessage:
    session: Session
    text: str
    received_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Matrix keys: matrix_event_id, matrix_room_id, matrix_thread_root

@dataclass
class OutboundMessage:
    session: Session
    text: str
    attachment: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Matrix keys: matrix_reaction, matrix_reply_to, matrix_thread_root
```

Both fields use `field(default_factory=dict)` / `None` so existing code and tests
require no changes.

## Configuration (`MatrixChannelConfig` — already in schema.py)

```yaml
matrix:
  homeserver: "https://matrix.example.org"
  user_id: "@squidbot:example.org"
  access_token: "syt_..."
  device_id: "SQUIDBOT"
  room_ids: ["!abc:example.org"]   # rooms to listen in
  group_policy: "mention"          # open | mention | allowlist
  allowlist: []                    # used when group_policy = allowlist
```

## Receiving Messages

### Event → InboundMessage

`MatrixChannel` registers a `RoomMessageText` callback on the nio client. The callback
filters events, then puts an `InboundMessage` on the queue.

**group_policy filtering:**

| Policy | Condition to accept |
|--------|---------------------|
| `open` | Any message in a configured room |
| `mention` | Message body contains `bot_user_id` |
| `allowlist` | Sender is in `allowlist` |

**Thread context:** If the event has `m.relates_to.rel_type == "m.thread"`, store
`event.source["content"]["m.relates_to"]["event_id"]` as `matrix_thread_root` in
`InboundMessage.metadata`.

### Incoming Attachments

For `m.image`, `m.file`, `m.audio`, `m.video` events:

1. Extract `mxc://` URI from `event.url` (unencrypted) or `event.file.url` (encrypted).
2. Call `client.download(server_name, media_id)` — matrix-nio uses
   `/_matrix/client/v1/media/download/` with `Authorization: Bearer` automatically.
3. For encrypted files: call `nio.crypto.attachments.decrypt_attachment(body, key_info)`
   where `key_info` is from `event.file`.
4. Determine file extension from `event.info.mimetype` via `mimetypes.guess_extension()`.
5. Compute SHA-256 of raw bytes; save to `/tmp/squidbot-<hex8>.<ext>`.
6. Set `InboundMessage.text = f"[Anhang: {filename} ({mimetype})] → {tmp_path}"`.

### Incoming Reactions (`m.reaction`)

Map to `InboundMessage.text = f"[Reaktion: {key}]"` where `key` is the emoji/text from
`event.content["m.relates_to"]["key"]`.

### Ignored Events

- Typing notifications (`m.typing`)
- Own messages (sender == bot user ID)
- Events older than the sync start time (historic backfill)

## Sending Messages

### Text

`streaming = False` — `AgentLoop` accumulates chunks and calls `send()` once with the
full text.

Event structure:
```json
{
  "msgtype": "m.text",
  "body": "<plain text>",
  "format": "org.matrix.custom.html",
  "formatted_body": "<rendered markdown>",
  "m.mentions": {},
  "m.relates_to": {
    "rel_type": "m.thread",
    "event_id": "<thread_root>",
    "m.in_reply_to": {"event_id": "<thread_root>"},
    "is_falling_back": true
  }
}
```

`m.relates_to` is only included when `OutboundMessage.metadata["matrix_thread_root"]` is set.
`MatrixChannel` copies `matrix_thread_root` from the corresponding `InboundMessage.metadata`
automatically when constructing the `OutboundMessage`.

Markdown → HTML via `markdown-it-py` (already transitively available via `rich`).

### Outgoing Attachments

When `OutboundMessage.attachment` is a `Path`:

1. **MIME detection:** `python-magic` (`magic.from_file(path, mime=True)`).
2. **Metadata extraction:**
   - Images (`image/*`): `PIL.Image.open(path)` → `w`, `h`.
   - Videos (`video/*`): `subprocess.run(["ffprobe", ...])` with JSON output →
     `w`, `h`, `duration` (ms).
   - Audio (`audio/*`): `ffprobe` → `duration` (ms).
   - All: `path.stat().st_size` → `size`.
   - Pillow/ffprobe failures are caught; missing fields are simply omitted from `info`.
3. **Upload:** `client.upload(data, content_type=mime, filename=path.name)` using
   `POST /_matrix/media/v3/upload`. Returns `mxc://` URI.
4. **msgtype selection:**

   | MIME prefix | msgtype |
   |-------------|---------|
   | `image/`    | `m.image` |
   | `video/`    | `m.video` |
   | `audio/`    | `m.audio` |
   | other       | `m.file` |

5. **Event content:**
   ```json
   {
     "msgtype": "m.image",
     "body": "filename.jpg",
     "filename": "filename.jpg",
     "url": "mxc://example.org/AbCdEf",
     "info": {"mimetype": "image/jpeg", "size": 31037, "w": 800, "h": 600},
     "m.mentions": {}
   }
   ```
   Thread `m.relates_to` is appended as with text messages when a thread root is set.

### Outgoing Reactions

When `OutboundMessage.metadata["matrix_reaction"]` is set:
```json
{
  "type": "m.reaction",
  "content": {
    "m.relates_to": {
      "rel_type": "m.annotation",
      "event_id": "<OutboundMessage.metadata['matrix_reply_to']>",
      "key": "👍"
    }
  }
}
```

## Typing Notifications

`ChannelPort.send_typing(room_id, typing)` is called by `AgentLoop` when it starts/stops
processing. `MatrixChannel.send_typing()` manages the keepalive loop internally — the core
has no knowledge of Matrix timeout semantics.

### Implementation

```python
TYPING_TIMEOUT_MS:        int   = 30_000   # server-side timeout
TYPING_KEEPALIVE_S:       float = 25.0     # 30s - 5s safety margin
TYPING_RETRY_DEFAULT_MS:  int   = 5_000    # fallback when 429 has no retry_after_ms
```

**`send_typing(room_id, True)`:**
1. Cancel any existing `_typing_task` for that room.
2. Set `_typing_active[room_id] = True`.
3. `asyncio.create_task(_typing_keepalive_loop(room_id))`.

**`_typing_keepalive_loop(room_id)`:**
```
while _typing_active[room_id]:
    resp = await client.room_typing(room_id, typing_state=True, timeout=TYPING_TIMEOUT_MS)
    if isinstance(resp, RoomTypingError):
        if resp.status_code == 429:
            retry_ms = resp.retry_after_ms or TYPING_RETRY_DEFAULT_MS
            await asyncio.sleep(retry_ms / 1000)
            continue
        # other errors: log and break
        break
    await asyncio.sleep(TYPING_KEEPALIVE_S)
```

**`send_typing(room_id, False)`:**
1. Set `_typing_active[room_id] = False`.
2. Cancel and await `_typing_task[room_id]` (if any).
3. Send `client.room_typing(room_id, typing_state=False)` (no timeout needed per spec).

**State:**
```python
_typing_active: dict[str, bool]                    # room_id → bool
_typing_tasks:  dict[str, asyncio.Task[None]]      # room_id → background task
```

Per-room state allows the bot to type in multiple rooms simultaneously without interference.

## New Dependencies

| Package | Use | Optional? |
|---------|-----|-----------|
| `python-magic>=0.4` | MIME detection for outgoing attachments | No (required for correct msgtype) |
| `Pillow>=10.0` | Image dimensions (w, h) for m.image | Yes (omit w/h if unavailable) |

`ffprobe` is an external binary (part of `ffmpeg`). It is invoked via `subprocess.run()`
with a try/except around `FileNotFoundError`. Video/audio duration and dimensions are
omitted if ffprobe is not in `PATH`.

## Error Handling

- `client.upload()` failure → log error, send text message only (no attachment).
- `client.download()` failure → `InboundMessage.text = "[Anhang nicht verfügbar: {error}]"`.
- Typing 429 → respect `retry_after_ms`, retry after delay.
- Typing other error → log warning, stop keepalive loop (do not crash).
- Sync errors → nio's `sync_forever()` handles reconnection internally.

## Testing Strategy

`tests/adapters/channels/test_matrix.py` uses `unittest.mock` to patch `nio.AsyncClient`.
No real homeserver needed.

Key test cases:
- `receive()` yields `InboundMessage` for accepted text events
- `receive()` skips own messages, non-allowlisted senders, typing events
- Incoming attachment downloads file, embeds path in text
- `send()` posts correct event structure (text, thread context, Markdown rendered)
- `send()` uploads attachment and posts m.image/m.file/etc. event
- `send_typing(True)` starts keepalive task; `send_typing(False)` stops it and sends stop event
- Typing keepalive sends again after `TYPING_KEEPALIVE_S` seconds
- Typing 429 retries after `retry_after_ms`

## File Changes Summary

| File | Change |
|------|--------|
| `squidbot/core/models.py` | Add `metadata: dict[str, Any]` to `InboundMessage`; add `attachment: Path \| None` and `metadata: dict[str, Any]` to `OutboundMessage` |
| `squidbot/adapters/channels/matrix.py` | New file: `MatrixChannel` |
| `squidbot/cli/main.py` | Wire `MatrixChannel` in `_run_gateway()`; add `_channel_loop()` helper |
| `pyproject.toml` | Add `python-magic>=0.4`, `Pillow>=10.0` to dependencies |
| `tests/adapters/channels/test_matrix.py` | New file: unit tests |
| `tests/core/test_models.py` | Extend existing tests for new fields |
