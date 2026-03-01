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

- URL: `event.url` -> `event.file.url` -> `event.source["content"]["file"]["url"]`
- MIME: `info.mimetype` fallback
- Filename: `event.body` fallback
- Encryption material:
  - direct attrs: `event.key`, `event.hashes`, `event.iv`
  - nested dict: `content.file.key`, `content.file.hashes`, `content.file.iv`

### Mention Policy Safety

Do not drop media events only because filename/body lacks textual mention markers in
`group_policy="mention"` rooms.

### Conditional BadEvent Fallback

Default behavior: no fallback.

If diagnostics show encrypted uploads arrive as non-media parser class and bypass callbacks,
add a guarded fallback path that only accepts media-shaped payloads.

## Debug Diagnostics

Add `logger.debug(...)` for:

1. Callback registration summary.
2. Event classification: `event_class`, `msgtype`, `has_url`, `has_file_url`, `has_key_material`.
3. Policy decision with reason codes (`accepted`, `policy_filtered`, `missing_media_url`, etc.).
4. Download/decrypt branch and failure reasons.
5. Embed decision (`embedded` vs fallback + reason).

Reason codes must be deterministic and greppable.

## Testing Strategy

Primary tests in `tests/adapters/channels/test_matrix.py`:

- callback registration includes both media classes
- encrypted `m.file` with `content.file.url` is processed
- decryption works with direct-attr and nested-file key-material forms
- mention-policy media acceptance is correct
- diagnostics emit expected reason codes

Conditional tests (only if fallback enabled):

- media-shaped `BadEvent` routes into media pipeline
- non-media `BadEvent` remains ignored

## Risks

- Over-accepting malformed events -> mitigate with strict media-shape checks.
- Debug noise -> debug-level only.
- Mention-policy regression -> explicit policy regression tests.
