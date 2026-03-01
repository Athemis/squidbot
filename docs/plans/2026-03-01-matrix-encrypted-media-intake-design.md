# Matrix Encrypted Media Intake Design

## Context

The previous Matrix attachment work fixed outbound uploads and basic inbound media handling.
We now have a production issue where user-uploaded encrypted `m.file` payloads are sometimes
not visible to the agent.

Observed shape includes `content.file.url` + encryption metadata (`key`, `hashes`, `iv`).

## Goals

1. Ensure inbound media intake handles both `RoomMessageMedia` and `RoomEncryptedMedia`.
2. Add debug diagnostics for event classification and routing decisions.
3. Normalize encrypted media extraction so different payload shapes are handled consistently.
4. Preserve existing size guardrails and embedding rules.
5. Add `BadEvent` fallback only if diagnostics prove media callbacks still miss events.

## Non-Goals

- Outbound media redesign.
- OCR/transcription.
- Cross-channel changes outside Matrix.

## Architecture

### Dual Media Callback Handling

Register inbound callbacks for:

- `RoomMessageMedia`
- `RoomEncryptedMedia`

Route both through one shared media processing path.

### Normalized Media Descriptor

Normalize extraction order:

**URL (three-level fallback):**

1. `event.url` — direct attribute on the event
2. `event.file.url` — nested `file` object attribute
3. `event.source.get("content", {}).get("file", {}).get("url", "")` — raw source dict; this
   is the shape produced by some clients for encrypted `m.file` events where `event.url` is
   empty string and `event.file` is `None`

Implement as `_extract_media_url(event: Any) -> str`:

```python
def _extract_media_url(event: Any) -> str:
    """Return the first non-empty mxc:// URL from event using three-level fallback."""
    return (
        getattr(event, "url", "") or
        getattr(getattr(event, "file", None), "url", "") or
        event.source.get("content", {}).get("file", {}).get("url", "") or
        ""
    )
```

**MIME:** `info.mimetype` fallback

**Filename:** `event.body` fallback

**Encryption material (two-form fallback):**

- Direct attrs: `event.key`, `event.hashes`, `event.iv`
- Nested dict: `event.source.get("content", {}).get("file", {})` — extract `key`, `hashes`,
  `iv` from this dict when direct attrs are absent (covers the case where `event.file is None`
  but key material is present in the raw source)

When decrypting, prefer direct attrs; fall back to the nested dict. Both paths must be covered
by tests.

### Mention Policy Safety

In `group_policy = "mention"` rooms, `_accept_event` checks `event.body` for the bot's name.
For media events `body` is the filename (e.g. `photo.jpg`), which never contains a mention —
causing silent drops.

**Fix:** In `_accept_event`, before the body-based mention check, detect whether the event is
a media event by inspecting `msgtype`:

```python
MEDIA_MSGTYPES = {"m.image", "m.file", "m.audio", "m.video"}

msgtype = event.source.get("content", {}).get("msgtype", "")
if msgtype in MEDIA_MSGTYPES:
    return True  # skip mention check for all media uploads
```

This applies to all media msgtypes (`m.image`, `m.file`, `m.audio`, `m.video`) — media uploads
in mention-policy rooms are always accepted regardless of the filename. Text events (`m.text`,
`m.notice`, `m.emote`) continue to require a textual mention.

### Conditional BadEvent Fallback

Default behavior: no fallback.

If diagnostics show encrypted uploads arrive as non-media parser class and bypass callbacks,
add a guarded fallback path that only accepts media-shaped payloads.

**Observable trigger criterion:** After deploying dual-callback registration (Task 3), send an
encrypted file from a Matrix client. Run with `LOG_LEVEL=DEBUG`. Search logs for
`MatrixChannel: _handle_media`. If no such line appears for the upload event, the fallback is
needed. If `_handle_media` is called, mark Task 5 as skipped.

## Debug Diagnostics

Add `logger.debug(...)` at five boundaries. Log format (exact strings, greppable):

| Boundary | Log format |
|----------|------------|
| Callback registration | `"MatrixChannel: registered callbacks classes={}"` |
| Event classification | `"MatrixChannel: classify event={} class={} msgtype={} has_url={} has_file_url={} has_key_material={}"` |
| Policy decision | `"MatrixChannel: policy event={} result={} reason={}"` |
| Download/decrypt branch | `"MatrixChannel: download event={} encrypted={} url={}"` |
| Embed decision | `"MatrixChannel: embed mxc={} embedded={} reason={}"` |

Reason codes must be deterministic and greppable: `accepted`, `policy_filtered`,
`missing_media_url`, `decryption_failed`, `size_exceeded`, `embedded`, `not_embedded`.

## Testing Strategy

Primary tests in `tests/adapters/channels/test_matrix.py`:

- Callback registration includes both media classes; `RoomEncryptedMedia` is registered
  specifically with `_handle_media` (not another handler)
- Encrypted `m.file` with `content.file.url` (and `event.file=None`, `event.url=""`) is
  processed — URL extracted from third fallback path
- Decryption with direct-attr key material (`event.key`, `event.hashes`, `event.iv`)
- Decryption with nested key material from `source["content"]["file"]["key/hashes/iv"]`
  when `event.file is None`
- Mention-policy: all media msgtypes are accepted without a textual mention marker
- Diagnostics emit expected reason codes (greppable format)
- Malformed `declared_size` (non-integer `size` field): download still attempted; document
  that preflight guard is bypassed gracefully and post-fetch guard applies

Conditional tests (only if fallback enabled — Task 5):

- Media-shaped `BadEvent` routes into media pipeline
- Non-media `BadEvent` remains ignored

## Risks

- Over-accepting malformed events -> mitigate with strict media-shape checks.
- Debug noise -> debug-level only.
- Mention-policy regression -> explicit policy regression tests covering all four media msgtypes.
