# Matrix Encrypted Media Intake Design

## Context

The previous Matrix attachment work fixed outbound uploads and basic inbound media handling.
We now have a production issue where user-uploaded encrypted `m.file` payloads are not
visible to the agent.

## Root Cause

Two separate failure modes, depending on room configuration:

**Case A — E2EE room (`e2ee_enabled=True`):** The bot has Megolm session keys. nio decrypts
`m.room.encrypted` wrappers via `parse_decrypted_event`, producing `RoomEncryptedFile` /
`RoomEncryptedImage` / `RoomEncryptedAudio` / `RoomEncryptedVideo` — all subclasses of
`RoomEncryptedMedia`. These events are **never registered** with an inbound callback in the
current squidbot implementation.

**Case B — Non-E2EE room (or client sending unencrypted `m.room.message` with
`content.file`):** The client omits `content.url` and puts the URL inside `content.file.url`.
nio's schema validator requires `content.url` for `m.room.message` media events and fails
validation → returns `BadEvent`. The existing `RoomMessageMedia` callback never fires.

## Event-Shape Taxonomy

Three distinct shapes arrive at the Matrix adapter (verified against nio source):

| Shape | nio type | `event.url` | Key-material attrs | When |
|---|---|---|---|---|
| Unencrypted file (`content.url`) | `RoomMessageFile` / `RoomMessageImage` / … | direct attr | — | Non-E2EE room, unencrypted upload |
| E2EE-decrypted file (Megolm) | `RoomEncryptedFile` / … (`RoomEncryptedMedia` subclass) | direct attr | `event.key` (dict), `event.iv` (str), `event.hashes` (dict) — all direct attrs | E2EE room, bot has session keys |
| Encrypted-metadata file without E2EE | `BadEvent` | absent | absent — in `source['content']['file']` | Non-E2EE room, client uses `content.file` shape |

nio's `add_event_callback` accepts a tuple of types: registering
`(RoomMessageMedia, RoomEncryptedMedia)` handles Cases A + unencrypted. Case B requires a
separate `BadEvent` callback.

## Goals

1. Register `RoomEncryptedMedia` callback (fix Case A — E2EE rooms).
2. Add `BadEvent` fallback for media-shaped bad events (fix Case B).
3. Fix pre-existing `decrypt_attachment` call-site bug: dict arg → correct positional string
   args extracted from `event.key["k"]`, `event.hashes["sha256"]`, `event.iv`.
4. Add debug diagnostics for event classification and routing decisions.
5. Preserve existing size guardrails and embedding rules.
6. Preserve mention-policy safety for media events.

## Non-Goals

- Outbound media redesign.
- OCR/transcription.
- Cross-channel changes outside Matrix.

## Architecture

### Dual Callback Registration

Register one callback covering both unencrypted and E2EE-decrypted events:

```python
MEDIA_EVENT_FILTER = (RoomMessageMedia, RoomEncryptedMedia)
client.add_event_callback(self._handle_media, MEDIA_EVENT_FILTER)
```

Register a separate callback for the `BadEvent` fallback:

```python
client.add_event_callback(self._handle_bad_event, nio.BadEvent)
```

### BadEvent Fallback

In `_handle_bad_event`, apply a strict media-shape guard before routing:

```python
MEDIA_MSGTYPES = {"m.image", "m.file", "m.audio", "m.video"}

def _is_media_shaped_bad_event(event: nio.BadEvent) -> bool:
    content = event.source.get("content", {})
    msgtype = content.get("msgtype", "")
    has_file_url = bool(content.get("file", {}).get("url", ""))
    return msgtype in MEDIA_MSGTYPES and has_file_url
```

Non-media bad events are ignored as before.

For `BadEvent`, URL and key material come from `source["content"]["file"]`:

```python
content_file = event.source["content"]["file"]
mxc_url = content_file["url"]
# Decrypt:
body = decrypt_attachment(
    body,
    content_file["key"]["k"],
    content_file["hashes"]["sha256"],
    content_file["iv"],
)
```

### Fix `decrypt_attachment` Call (Pre-existing Bug)

The existing code at `matrix.py:773` calls `decrypt_attachment_fn(body, key_info)` passing a
dict. The correct signature is `decrypt_attachment(ciphertext, key, hash, iv)` with four
positional string args.

For `RoomEncryptedMedia` events (direct attrs):

```python
body = decrypt_attachment(
    body,
    event.key["k"],
    event.hashes["sha256"],
    event.iv,
)
```

Both call sites must be covered by tests that verify actual argument shapes.

### Mention Policy Safety

In `group_policy = "mention"` rooms, `_accept_event` checks `event.body` for the bot's name.
For media events `body` is the filename, which never contains a mention.

**Fix:** In `_accept_event`, before the body-based mention check, detect media events via
`msgtype`:

```python
MEDIA_MSGTYPES = {"m.image", "m.file", "m.audio", "m.video"}

msgtype = event.source.get("content", {}).get("msgtype", "")
if msgtype in MEDIA_MSGTYPES:
    return True  # skip mention check for all media uploads
```

Applies to all four media msgtypes. Text events (`m.text`, `m.notice`, `m.emote`) continue
to require a textual mention.

> **Note for squidbot:** The nanobot-redux implementation uses
> `_is_bot_mentioned_from_mx_mentions` which reads `m.mentions.user_ids` from the source
> dict — this avoids the body/filename confusion entirely. That is the cleaner long-term fix,
> but is out of scope for this feature.

## Debug Diagnostics

Add `logger.debug(...)` at five boundaries. Log format (exact strings, greppable):

| Boundary | Log format |
|---|---|
| Callback registration | `"MatrixChannel: registered callbacks classes={}"` |
| Event classification | `"MatrixChannel: classify event={} class={} msgtype={} has_url={} has_file_url={} has_key_material={}"` |
| Policy decision | `"MatrixChannel: policy event={} result={} reason={}"` |
| Download/decrypt branch | `"MatrixChannel: download event={} encrypted={} url={}"` |
| Embed decision | `"MatrixChannel: embed mxc={} embedded={} reason={}"` |

Reason codes: `accepted`, `policy_filtered`, `missing_media_url`, `decryption_failed`,
`size_exceeded`, `embedded`, `not_embedded`.

## Testing Strategy

Primary tests in `tests/adapters/channels/test_matrix.py`:

- `(RoomMessageMedia, RoomEncryptedMedia)` tuple is registered with `_handle_media`
- `BadEvent` callback is registered with `_handle_bad_event`
- `BadEvent` with `m.file` + `content.file.url` routes into media pipeline
- Non-media `BadEvent` is ignored
- `RoomEncryptedFile` event: `decrypt_attachment` called with `event.key["k"]`,
  `event.hashes["sha256"]`, `event.iv` (positional strings — not a dict)
- `BadEvent` encrypted file: `decrypt_attachment` called with key material from
  `source["content"]["file"]`
- Mention-policy: all four media msgtypes accepted without textual mention marker
- Diagnostics emit expected reason codes
- Malformed `declared_size` (non-integer): download still attempted; post-fetch guard applies

## Risks

- BadEvent over-acceptance: mitigated by `_is_media_shaped_bad_event` strict shape check.
- Debug noise: debug-level only.
- Mention-policy regression: explicit regression tests for all four media msgtypes.
- Decrypt call signature change: covered by decrypt tests verifying positional string args.
