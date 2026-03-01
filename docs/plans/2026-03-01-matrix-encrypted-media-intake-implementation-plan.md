# Matrix Encrypted Media Intake Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure encrypted and unencrypted Matrix uploads are consistently surfaced to the agent.

**Architecture:** Add diagnostics first, then implement dual media callback handling and
normalized encrypted payload extraction in the Matrix adapter. Keep current guardrails,
validate mention-policy media behavior, and add a `BadEvent` fallback only if logs prove
callback miss.

**Tech Stack:** Python 3.14, matrix-nio, Loguru, pytest, mypy --strict, ruff.

---

### Task 1: Add failing tests for encrypted media intake

**Files:**
- Modify: `tests/adapters/channels/test_matrix.py`

**Step 1: Write failing callback coverage test**

Assert both that `nio.RoomEncryptedMedia` is registered AND that it is registered with
`_handle_media` specifically (not another handler):

```python
async def test_registers_room_message_and_room_encrypted_media_callbacks() -> None:
    # assert nio.RoomEncryptedMedia in registered_types
    # assert any(
    #     c.args == (ch._handle_media, nio.RoomEncryptedMedia)
    #     for c in fake_client.add_event_callback.call_args_list
    # ), "RoomEncryptedMedia must be registered with _handle_media, not another handler"
    ...
```

**Step 2: Write failing encrypted payload test (third URL fallback)**

This tests the shape where `event.url = ""`, `event.file = None`, but
`source["content"]["file"]["url"]` contains the mxc URL:

```python
async def test_encrypted_file_with_content_file_url_is_processed() -> None:
    # event.url = "", event.file = None
    # event.source["content"]["file"]["url"] = "mxc://..."
    # assert download called with correct server_name and media_id
    ...
```

**Step 3: Write failing encrypted payload test (key material from source)**

Tests the case where key material (`key`, `iv`, `hashes`) is in `source["content"]["file"]`
and `event.file is None`:

```python
async def test_encrypted_file_key_material_extracted_from_source_when_event_file_is_none() -> None:
    # event.file = None, event.url = ""
    # event.source["content"]["file"] = {"url": "mxc://...", "key": {...}, "iv": "...", "hashes": {...}}
    # assert decrypt called with key material from source
    ...
```

**Step 4: Write failing mention-policy media test**

```python
async def test_media_event_not_dropped_only_due_to_filename_without_mention() -> None:
    ...
```

**Step 5: Write test for malformed declared_size**

```python
async def test_malformed_declared_size_does_not_block_download() -> None:
    # event.info.size = "not-a-number"
    # assert download is still attempted (post-fetch guard applies, preflight guard bypassed)
    ...
```

**Step 6: Run tests to verify RED**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "encrypted_file or callback or mention or declared_size" -v`
Expected: FAIL.

**Step 7: Commit red tests**

```bash
git add tests/adapters/channels/test_matrix.py
git commit -m "test(matrix): add failing encrypted media intake coverage"
```

### Task 2: Add parser/routing diagnostics

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `tests/adapters/channels/test_matrix.py`

**Step 1: Write failing diagnostic assertion test**

Assert the exact log format strings from the design doc:

```python
async def test_debug_logs_include_event_class_and_media_shape() -> None:
    # capture loguru output at DEBUG level
    # assert log contains: "MatrixChannel: classify event=... class=... msgtype=... has_url=... has_file_url=... has_key_material=..."
    # assert log contains: "MatrixChannel: policy event=... result=... reason=..."
    ...
```

**Step 2: Run to verify RED**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "debug_logs_include_event_class" -v`
Expected: FAIL.

**Step 3: Implement debug logging boundaries**

Add `logger.debug(...)` at five boundaries using the exact log format from the design doc:

| Boundary | Log format |
|----------|------------|
| Callback registration | `"MatrixChannel: registered callbacks classes={}"` |
| Event classification | `"MatrixChannel: classify event={} class={} msgtype={} has_url={} has_file_url={} has_key_material={}"` |
| Policy decision | `"MatrixChannel: policy event={} result={} reason={}"` |
| Download/decrypt branch | `"MatrixChannel: download event={} encrypted={} url={}"` |
| Embed decision | `"MatrixChannel: embed mxc={} embedded={} reason={}"` |

Reason codes: `accepted`, `policy_filtered`, `missing_media_url`, `decryption_failed`,
`size_exceeded`, `embedded`, `not_embedded`.

**Step 4: Re-run diagnostic tests**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "debug_logs_include_event_class" -v`
Expected: PASS.

**Step 5: Commit diagnostics**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "feat(matrix): add inbound media parser diagnostics"
```

### Task 3: Implement dual callback handling + normalized extraction

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `tests/adapters/channels/test_matrix.py`

**Step 1: Register both callback classes**

- `nio.RoomMessageMedia`
- `nio.RoomEncryptedMedia` — registered with `_handle_media`

**Step 2: Implement `_extract_media_url` helper**

Three-level URL fallback with safe `.get()` access throughout:

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

**Step 3: Implement key-material extraction helper**

When `event.file is None`, extract key material from `source["content"]["file"]`:

```python
def _extract_key_material(event: Any) -> tuple[dict, str, dict] | None:
    """Return (key, iv, hashes) from event or source, or None if unavailable."""
    if getattr(event, "key", None):
        return event.key, event.iv, event.hashes
    source_file = event.source.get("content", {}).get("file", {})
    if source_file.get("key"):
        return source_file["key"], source_file["iv"], source_file["hashes"]
    return None
```

**Step 4: Route both classes through same media processing path**

**Step 5: Run focused tests**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "encrypted_file or callback" -v`
Expected: PASS.

**Step 6: Commit implementation**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "fix(matrix): handle room media and encrypted media event classes"
```

### Task 4: Validate mention-policy behavior for media events

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `tests/adapters/channels/test_matrix.py`

**Step 1: Write failing media policy regression tests**

Test all four media msgtypes:

```python
async def test_mention_policy_accepts_media_event_without_textual_mention_marker() -> None:
    # m.image, m.file, m.audio, m.video — all must be accepted in mention-policy rooms
    # even when body (filename) contains no bot mention
    ...
```

**Step 2: Run to verify RED**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "mention_policy_accepts_media_event" -v`
Expected: FAIL.

**Step 3: Implement mention-policy fix in `_accept_event`**

Before the body-based mention check, add:

```python
MEDIA_MSGTYPES = {"m.image", "m.file", "m.audio", "m.video"}

msgtype = event.source.get("content", {}).get("msgtype", "")
if msgtype in MEDIA_MSGTYPES:
    return True  # skip mention check for all media uploads
```

This bypasses the mention check for all four media msgtypes. Text events (`m.text`,
`m.notice`, `m.emote`) continue to require a textual mention.

**Step 4: Re-run mention policy subset**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "mention_policy" -v`
Expected: PASS.

**Step 5: Commit policy fix**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "fix(matrix): avoid false mention-policy drops for media events"
```

---

**Decision gate (Task 5 trigger):** After deploying Task 3 and Task 4, run
`LOG_LEVEL=DEBUG uv run squidbot gateway` and send an encrypted file from a Matrix client.
Search logs for `MatrixChannel: _handle_media`. If no such line appears for the upload event,
proceed to Task 5. If `_handle_media` is called, mark Task 5 as skipped and proceed to Task 6.

---

### Task 5 (Conditional): Add BadEvent fallback if diagnostics prove callback miss

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `tests/adapters/channels/test_matrix.py`

**Only run if the Task 5 decision gate above is triggered (no `_handle_media` log appears).**

**Step 1: Add failing fallback test**

```python
async def test_bad_event_with_media_shape_routes_to_media_pipeline() -> None:
    ...
```

**Step 2: Verify RED**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "bad_event" -v`
Expected: FAIL.

**Step 3: Implement guarded fallback**

Only route media-shaped bad events (`msgtype` in `MEDIA_MSGTYPES` + `content.file.url`
or `content.url`).

**Step 4: Re-run fallback tests**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "bad_event" -v`
Expected: PASS.

**Step 5: Commit fallback**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "fix(matrix): add guarded bad-event fallback for encrypted media"
```

### Task 6: Full verification

**Files:**
- Modify: none

**Step 1: Run matrix adapter suite**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -v`
Expected: PASS.

**Step 2: Run lint**

Run: `uv run ruff check .`
Expected: PASS.

**Step 3: Run format check**

Run: `uv run ruff format . --check`
Expected: PASS.

**Step 4: Run typing**

Run: `uv run mypy squidbot/`
Expected: PASS.

**Step 5: Run full tests**

Run: `uv run pytest`
Expected: PASS.

**Step 6: Final integration commit**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "fix(matrix): ensure encrypted inbound file uploads reach agent context"
```
