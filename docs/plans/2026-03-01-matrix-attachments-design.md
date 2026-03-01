# Matrix Attachment Support: Inbound Multimodal + Outbound Upload Fix

**Date:** 2026-03-01
**Revised:** 2026-03-01 (Gap Analysis fixes)

## Problem Statement

The Matrix channel adapter has two broken attachment flows:

1. **Outbound (agent → user):** `_send_attachment()` passes a `lambda *_: data` as `data_provider` to `nio.AsyncClient.upload()`. The nio API expects a file-like object (`io.BytesIO` or similar), not a callable. This causes the upload to fail silently or raise at runtime.

2. **Inbound (user → agent):** `_handle_media()` downloads the attachment, saves it to `/tmp/`, and passes only a plain text string `"[Anhang: foto.jpg (image/jpeg)] → /tmp/squidbot-abc12345.jpg"` to the agent. The agent can request file content via tools, but cannot *see* images without a tool call. Vision-capable LLMs expect images as OpenAI multimodal content blocks embedded in the message.

## Goals

- Fix the outbound upload bug so agents can send files as Matrix media events.
- Support inbound images as multimodal content so vision models can directly process them.
- Non-image attachments (PDF, audio, video, binary) continue to be passed as a local file path in text — the agent uses `read_file` or other tools to access them.
- Multiple outbound attachments per reply (`OutboundMessage.attachment: list[Path]` instead of `Path | None`).

## Non-Goals

- Audio transcription (Whisper) — separate concern.
- PDF multimodal blocks (not OpenAI-compatible without provider extensions).
- Encrypted upload support (defer; nio's E2EE upload path returns separate key info).
- Image resizing/compression — future enhancement if needed.

## Reference

nanobot-redux implements a similar approach in `nanobot/channels/matrix.py`:
- Upload: opens file with `resolved.open("rb")`, passes file object directly to `client.upload()`.
- Inbound: downloads bytes, decrypts if encrypted, saves to `~/.nanobot/media/matrix/`, passes local path in metadata dict and as text marker.
- Does **not** embed Base64 images in LLM context — relies on separate tool calls.

squidbot's design differs: we *do* embed images as Base64 for vision models, which is intentional.

## Architecture

### Component Map

```
squidbot/core/models.py              ← Message.content type + OutboundMessage.attachment type
squidbot/core/agent.py               ← user_message type + Message construction
squidbot/adapters/channels/matrix.py ← upload fix + inbound multimodal builder
squidbot/adapters/channels/email.py  ← adapt to list[Path] (attach all existing files)
squidbot/adapters/channels/cli.py    ← no change (ignores attachment field)
squidbot/cli/gateway.py              ← dispatch multimodal_content to agent.run()
squidbot/config/schema.py            ← inbound/outbound media thresholds
tests/core/test_models.py            ← Message.to_openai_dict multimodal tests
tests/adapters/channels/test_matrix.py ← upload + inbound + outbound tests
tests/config/test_schema.py          ← config default tests
```

### Cross-Channel Attachment Contract

| Channel | `OutboundMessage.attachment` Behavior |
|---------|---------------------------------------|
| Matrix  | Iterate all paths, upload+send each as separate media event |
| Email   | Iterate all paths and add each existing file as MIME attachment |
| CLI     | Ignore attachment field (text-only) |

**Rationale:** Attaching multiple files to one email is a normal and useful behavior; Matrix maps each file to one media event; CLI remains text-only.

### `Message.content` — Multimodal Extension

OpenAI's chat completion API accepts either:
- `"content": "plain text"` — scalar string
- `"content": [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}]` — multimodal list

`Message.content` is changed from `str` to `str | list[dict[str, Any]]`.

`Message.to_openai_dict()` already serializes `content` — it works for both types without change since Python dicts serialize correctly to JSON.

### `OutboundMessage.attachment` — List Extension

Changed from `Path | None` to `list[Path]`. Default is `[]` (empty list).

**Migration for existing channels:**
- **Matrix:** Iterate list, send each as separate media event
- **Email:** Iterate list and attach each existing file to one outgoing email
- **CLI:** No change (already ignores attachment)

### Inbound Multimodal Flow

```
nio RoomMessageMedia event
  ↓
MatrixChannel._handle_media(room, event)
  ↓
MatrixChannel._download_attachment(event) → (text: str, multimodal_content: list[dict] | None)
  ↓
  if MIME in EMBEDDABLE_IMAGE_MIMES and size ≤ max_embed_bytes:
    read bytes → base64 encode → build image_url block
    multimodal_content = [
      {"type": "text", "text": "[Anhang: foto.jpg (image/jpeg)] → /tmp/..."},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    ]
  else:
    multimodal_content = None  # text-only fallback
  ↓
InboundMessage(
  session=...,
  text="[Anhang: foto.jpg (image/jpeg)] → /tmp/squidbot-abc12345.jpg",
  multimodal_content=multimodal_content,  # new optional field
  metadata=...
)
  ↓
cli/gateway.py: _channel_loop_with_state() / _channel_loop()
  ↓
agent.run(user_message=msg.multimodal_content or msg.text, ...)
  ↓
Message(role="user", content=multimodal_content or text)
  ↓
LLM API: {"role": "user", "content": [...]}
```

### Outbound Upload Fix

Current bug (line 579):
```python
resp = await self._client.upload(
    data_provider=lambda *_: data,  # ← WRONG: not a file-like
    ...
)
```

Fix: pass `io.BytesIO(data)` as positional argument:
```python
resp = await self._client.upload(
    io.BytesIO(data),
    content_type=mime,
    filename=path.name,
    filesize=len(data),
)
```

`upload()` accepts either a `DataProvider` callable with signature `(offset, limit) -> bytes` OR a SynchronousFile (BytesIO, BufferedReader, etc.). `BytesIO` is the simplest and correct choice for in-memory data.

### Size Limits, MIME Allowlist, and Homeserver Upload Cap

**Two-threshold policy:**

| Threshold | Default | Purpose |
|-----------|---------|---------|
| `max_download_bytes` | 50 MB | Hard cap on download size (memory protection) |
| `max_embed_bytes` | 2 MB | Cap for Base64 embedding (LLM request budget) |
| `max_outbound_upload_bytes` | 20 MB | Local cap for outbound upload attempts |

**MIME Allowlist for Embedding:**

```python
EMBEDDABLE_IMAGE_MIMES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
})
```

**SVG (`image/svg+xml`) is explicitly excluded** — it's XML, not a raster format, and can cause provider-specific handling issues.

**What happens for files outside the allowlist?**
- They are still downloaded (unless blocked by `max_download_bytes`) and persisted locally.
- They are forwarded as text-path context only (no `image_url` Base64 block).
- This preserves tool-based access (`read_file`, etc.) without bloating LLM payloads.

**Homeserver upload limit integration (`m.upload.size`):**
- Matrix homeservers may expose upload cap via `/_matrix/media/*/config` (`m.upload.size`).
- Channel resolves this once (cached) and computes:

`effective_outbound_limit = min(max_outbound_upload_bytes, server_upload_limit_if_present)`

- If server limit is unavailable, only local threshold applies.
- If a file exceeds the effective limit, skip upload and log debug reason `exceeds_outbound_limit`.

**Fallback reasons logged at DEBUG level:**
- `non-image` — MIME not in allowlist
- `exceeds_embed_limit` — size > max_embed_bytes
- `exceeds_download_limit` — size > max_download_bytes (skip download entirely)

### Gateway Dispatch Path

**Critical:** The inbound message dispatch happens in `squidbot/cli/gateway.py`, NOT `cli/main.py`.

Files to modify:
- `squidbot/cli/gateway.py:139-145` (`_channel_loop_with_state`)
- `squidbot/cli/gateway.py:177-183` (`_channel_loop`)

Both loops call `agent.run()`. Update to pass `msg.multimodal_content or msg.text`.

## Error Handling

| Failure | Behavior |
|---------|----------|
| Image download fails | Text `[Anhang nicht verfügbar: ...]`, multimodal_content=None |
| Base64 encoding error | Text-path fallback, log warning |
| Image > embed limit | Text-path fallback, log debug with reason |
| Declared size > download limit | Skip download, text `[Anhang: zu groß]`, log debug |
| MIME not in allowlist | Download + local persistence + text-path fallback, log debug |
| Outbound file > effective outbound limit | Skip upload, log debug (`exceeds_outbound_limit`) |
| Upload fails (outbound) | `logger.error` + skip file |
| All attachments fail | Text reply still sent |

## Testing Strategy

### Unit Tests

- `test_message_to_openai_dict_multimodal`: assert list-content serializes correctly
- `test_outbound_message_attachment_defaults_to_empty_list`
- `test_outbound_message_attachment_accepts_list`
- `test_inbound_message_multimodal_content_default_none`
- `test_inbound_message_multimodal_content_set`
- `test_download_attachment_image_returns_multimodal`: mock download → check base64 block
- `test_download_attachment_non_image_returns_no_multimodal`: PDF → text only
- `test_download_attachment_too_large_returns_text_only`: oversized image → text fallback
- `test_download_attachment_mime_not_allowed`: SVG → text fallback
- `test_download_attachment_declared_size_exceeds_download_limit`: skip download
- `test_send_attachment_uses_bytesio`: mock upload → assert BytesIO called
- `test_send_multiple_attachments`: two paths → two upload calls
- `test_email_channel_attaches_all_files`: list[Path] → all existing files attached
- `test_matrix_channel_config_media_defaults`: config defaults = 2MB embed, 50MB download, 20MB outbound local cap
- `test_effective_outbound_limit_uses_server_upload_size_when_available`
- `test_outbound_upload_skips_when_exceeding_effective_limit`

### Integration Tests

- `test_gateway_forwards_multimodal_content`: gateway dispatch passes multimodal list to agent.run()
- `test_gateway_falls_back_to_text_when_no_multimodal`: text-only InboundMessage → str passed

## Debug Logging

All attachment decision points emit `logger.debug()` (silent in production, visible with `LOG_LEVEL=DEBUG`):

**Outbound (`_send_attachment`):**
- Uploading: path, mime, size_bytes
- Uploaded: mxc_uri, path
- Sent: room_id, msgtype, mxc_uri
- Failed: error details

**Inbound (`_download_attachment`):**
- Downloading: mxc, filename
- Downloaded: mxc, size_bytes, mime
- Embedded: mxc, size_bytes (multimodal)
- Text-path fallback: mxc, mime, reason

**Gateway dispatch:**
- Dispatching: session_id, multimodal=True/False

## Security Considerations

1. **Memory protection:** `max_download_bytes` prevents OOM from malicious large files
2. **Request budget:** `max_embed_bytes` prevents LLM API failures from oversized payloads
3. **MIME allowlist:** Reduces attack surface from unusual image formats
4. **Path traversal:** Existing workspace restrictions apply to outbound attachments
5. **SVG exclusion:** Prevents potential XML-based attacks via image embedding
