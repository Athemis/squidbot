# Matrix Encrypted Media Intake Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure encrypted and unencrypted Matrix uploads are consistently surfaced to the agent.

**Architecture:** Fix two separate failure modes: (A) register `RoomEncryptedMedia` callback for
E2EE Megolm rooms, (B) add `BadEvent` fallback for non-E2EE clients using `content.file` shape.
Fix the pre-existing `decrypt_attachment` call-site bug (dict arg → positional string args).
Add diagnostics. Preserve mention-policy safety.

**Reference implementation:** `nanobot-redux` — `nanobot/channels/matrix.py` — this has
a working dual-callback setup (`MATRIX_MEDIA_EVENT_FILTER = (RoomMessageMedia, RoomEncryptedMedia)`)
and correct `_decrypt_media_bytes` using positional string args. Port the relevant patterns.

**Tech Stack:** Python 3.14, matrix-nio, Loguru, pytest, mypy --strict, ruff.

---

### Task 1: Add failing tests for encrypted media intake

**Files:**
- Modify: `tests/adapters/channels/test_matrix.py`

**Step 1: Write failing callback registration test**

Assert that `(RoomMessageMedia, RoomEncryptedMedia)` tuple is registered with `_handle_media`,
AND that `BadEvent` is registered with `_handle_bad_event`:

```python
async def test_registers_room_message_media_encrypted_media_and_bad_event_callbacks() -> None:
    # assert any(
    #     c.args == (ch._handle_media,) and
    #     set(c.args[1]) == {nio.RoomMessageMedia, nio.RoomEncryptedMedia}  # tuple filter
    #     for c in fake_client.add_event_callback.call_args_list
    # )
    # assert any(
    #     c.args == (ch._handle_bad_event, nio.BadEvent)
    #     for c in fake_client.add_event_callback.call_args_list
    # )
    ...
```

**Step 2: Write failing test — BadEvent with media shape routes to pipeline**

```python
async def test_bad_event_with_media_shape_routes_to_media_pipeline() -> None:
    # event = nio.BadEvent with source["content"] = {
    #     "msgtype": "m.file", "body": "doc.pdf",
    #     "file": {"url": "mxc://example.com/abc", "key": {...}, "iv": "...", "hashes": {...}}
    # }
    # assert InboundMessage queued with attachment
    ...
```

**Step 3: Write failing test — non-media BadEvent is ignored**

```python
async def test_bad_event_without_media_shape_is_ignored() -> None:
    # event = nio.BadEvent with source["content"] = {"msgtype": "m.text", "body": "hi"}
    # assert no InboundMessage queued
    ...
```

**Step 4: Write failing test — RoomEncryptedMedia decrypt uses positional string args**

```python
async def test_room_encrypted_media_decrypt_uses_key_k_and_hashes_sha256() -> None:
    # event = nio.RoomEncryptedFile with:
    #   event.url = "mxc://example.com/enc"
    #   event.key = {"k": "base64key", "kty": "oct", ...}
    #   event.hashes = {"sha256": "base64hash"}
    #   event.iv = "base64iv"
    # mock decrypt_attachment, assert called with (ciphertext, "base64key", "base64hash", "base64iv")
    # NOT called with a dict
    ...
```

**Step 5: Write failing test — BadEvent decrypt uses source["content"]["file"] key material**

```python
async def test_bad_event_media_decrypt_uses_source_content_file_key_material() -> None:
    # BadEvent with source["content"]["file"] = {
    #   "url": "mxc://...", "key": {"k": "base64key", ...},
    #   "iv": "base64iv", "hashes": {"sha256": "base64hash"}
    # }
    # mock decrypt_attachment, assert called with positional strings from file dict
    ...
```

**Step 6: Write failing mention-policy media test**

```python
async def test_media_event_not_dropped_only_due_to_filename_without_mention() -> None:
    # group_policy = "mention", event msgtype in {m.image, m.file, m.audio, m.video}
    # event.body = "photo.jpg" (no bot mention)
    # assert event is accepted
    ...
```

**Step 7: Write failing test — malformed declared_size does not block download**

```python
async def test_malformed_declared_size_does_not_block_download() -> None:
    # event.info.size = "not-a-number"
    # assert download is still attempted (post-fetch guard applies)
    ...
```

**Step 8: Run tests to verify RED**

```
uv run pytest tests/adapters/channels/test_matrix.py \
  -k "bad_event or encrypted_media or callback or mention or declared_size" -v
```

Expected: FAIL on all new tests.

**Step 9: Commit red tests**

```bash
git add tests/adapters/channels/test_matrix.py
git commit -m "test(matrix): add failing encrypted media intake coverage"
```

---

### Task 2: Add parser/routing diagnostics

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `tests/adapters/channels/test_matrix.py`

**Step 1: Write failing diagnostic assertion test**

```python
async def test_debug_logs_include_event_class_and_media_shape() -> None:
    # capture loguru output at DEBUG level
    # assert log contains:
    #   "MatrixChannel: classify event=... class=... msgtype=... has_url=... has_file_url=... has_key_material=..."
    #   "MatrixChannel: policy event=... result=... reason=..."
    ...
```

**Step 2: Run to verify RED**

```
uv run pytest tests/adapters/channels/test_matrix.py -k "debug_logs_include_event_class" -v
```

Expected: FAIL.

**Step 3: Implement debug logging boundaries**

Add `logger.debug(...)` at five boundaries using exact log format from design doc:

| Boundary | Log format |
|---|---|
| Callback registration | `"MatrixChannel: registered callbacks classes={}"` |
| Event classification | `"MatrixChannel: classify event={} class={} msgtype={} has_url={} has_file_url={} has_key_material={}"` |
| Policy decision | `"MatrixChannel: policy event={} result={} reason={}"` |
| Download/decrypt branch | `"MatrixChannel: download event={} encrypted={} url={}"` |
| Embed decision | `"MatrixChannel: embed mxc={} embedded={} reason={}"` |

Reason codes: `accepted`, `policy_filtered`, `missing_media_url`, `decryption_failed`,
`size_exceeded`, `embedded`, `not_embedded`.

**Step 4: Re-run diagnostic test**

```
uv run pytest tests/adapters/channels/test_matrix.py -k "debug_logs_include_event_class" -v
```

Expected: PASS.

**Step 5: Commit diagnostics**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "feat(matrix): add inbound media parser diagnostics"
```

---

### Task 3: Implement dual callback registration + fix decrypt call

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`

**Step 1: Define `MEDIA_EVENT_FILTER` constant**

```python
MEDIA_EVENT_FILTER = (nio.RoomMessageMedia, nio.RoomEncryptedMedia)
```

**Step 2: Register callbacks in `_register_callbacks`**

```python
self._client.add_event_callback(self._handle_media, MEDIA_EVENT_FILTER)
self._client.add_event_callback(self._handle_bad_event, nio.BadEvent)
```

**Step 3: Implement `_handle_bad_event`**

```python
async def _handle_bad_event(self, room: nio.MatrixRoom, event: nio.BadEvent) -> None:
    """Route media-shaped BadEvent into the media pipeline; ignore all others."""
    if not _is_media_shaped_bad_event(event):
        return
    # delegate to shared media processing path
```

**Step 4: Implement `_is_media_shaped_bad_event`**

```python
MEDIA_MSGTYPES = {"m.image", "m.file", "m.audio", "m.video"}

def _is_media_shaped_bad_event(event: nio.BadEvent) -> bool:
    content = event.source.get("content", {})
    msgtype = content.get("msgtype", "")
    has_file_url = bool(content.get("file", {}).get("url", ""))
    return msgtype in MEDIA_MSGTYPES and has_file_url
```

**Step 5: Fix `decrypt_attachment` call (pre-existing bug at line ~773)**

Replace the dict-based call with positional string extraction. For `RoomEncryptedMedia`
events (direct attrs):

```python
from nio.crypto.attachments import decrypt_attachment
from nio.exceptions import EncryptionError

key = event.key.get("k") if isinstance(event.key, dict) else None
sha256 = event.hashes.get("sha256") if isinstance(event.hashes, dict) else None
iv = event.iv if isinstance(event.iv, str) else None
if not (key and sha256 and iv):
    # log warning, return error marker
body = decrypt_attachment(body, key, sha256, iv)
```

For `BadEvent` (source dict path):

```python
content_file = event.source["content"]["file"]
key = content_file.get("key", {}).get("k")
sha256 = content_file.get("hashes", {}).get("sha256")
iv = content_file.get("iv")
if not (key and sha256 and iv):
    # log warning, return error marker
body = decrypt_attachment(body, key, sha256, iv)
```

**Step 6: Run focused tests**

```
uv run pytest tests/adapters/channels/test_matrix.py \
  -k "bad_event or callback or encrypted_media" -v
```

Expected: PASS.

**Step 7: Commit**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "fix(matrix): register RoomEncryptedMedia callback and BadEvent fallback"
```

---

### Task 4: Validate mention-policy behavior for media events

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `tests/adapters/channels/test_matrix.py`

**Step 1: Run failing mention-policy test from Task 1 Step 6**

```
uv run pytest tests/adapters/channels/test_matrix.py -k "mention_policy" -v
```

Expected: FAIL.

**Step 2: Add `MEDIA_MSGTYPES` bypass in `_accept_event`**

Before the body-based mention check:

```python
MEDIA_MSGTYPES = {"m.image", "m.file", "m.audio", "m.video"}

msgtype = event.source.get("content", {}).get("msgtype", "")
if msgtype in MEDIA_MSGTYPES:
    return True  # skip mention check for all media uploads
```

**Step 3: Re-run mention-policy tests**

```
uv run pytest tests/adapters/channels/test_matrix.py -k "mention_policy" -v
```

Expected: PASS.

**Step 4: Commit**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "fix(matrix): avoid false mention-policy drops for media events"
```

---

### Task 5: Full verification

**Files:**
- Modify: none

**Step 1: Run full matrix adapter suite**

```
uv run pytest tests/adapters/channels/test_matrix.py -v
```

Expected: all PASS.

**Step 2: Run lint**

```
uv run ruff check .
```

Expected: PASS.

**Step 3: Run format check**

```
uv run ruff format . --check
```

Expected: PASS.

**Step 4: Run type-check**

```
uv run mypy squidbot/
```

Expected: PASS.

**Step 5: Run full test suite**

```
uv run pytest
```

Expected: PASS.

**Step 6: Final integration commit**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "fix(matrix): ensure encrypted inbound file uploads reach agent context"
```
