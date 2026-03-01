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

```python
async def test_registers_room_message_and_room_encrypted_media_callbacks() -> None:
    ...
```

**Step 2: Write failing encrypted payload test**

```python
async def test_encrypted_file_with_content_file_url_is_processed() -> None:
    ...
```

**Step 3: Write failing mention-policy media test**

```python
async def test_media_event_not_dropped_only_due_to_filename_without_mention() -> None:
    ...
```

**Step 4: Run tests to verify RED**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "encrypted_file or callback or mention" -v`
Expected: FAIL.

**Step 5: Commit red tests**

```bash
git add tests/adapters/channels/test_matrix.py
git commit -m "test(matrix): add failing encrypted media intake coverage"
```

### Task 2: Add parser/routing diagnostics

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `tests/adapters/channels/test_matrix.py`

**Step 1: Write failing diagnostic assertion test**

```python
async def test_debug_logs_include_event_class_and_media_shape() -> None:
    ...
```

**Step 2: Run to verify RED**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "debug_logs_include_event_class" -v`
Expected: FAIL.

**Step 3: Implement debug logging boundaries**

Add debug logs for callback registration, event classification, policy decisions,
download/decrypt branches, and embed decisions.

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
- `nio.RoomEncryptedMedia`

**Step 2: Implement normalized URL/key extraction helper**

Precedence:
- URL: `event.url` -> `event.file.url` -> `event.source.content.file.url`
- key material: direct attrs first, then nested file dict

**Step 3: Route both classes through same media processing path**

**Step 4: Run focused tests**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "encrypted_file_with_content_file_url or callback" -v`
Expected: PASS.

**Step 5: Commit implementation**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "fix(matrix): handle room media and encrypted media event classes"
```

### Task 4: Validate mention-policy behavior for media events

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `tests/adapters/channels/test_matrix.py`

**Step 1: Write failing media policy regression test**

```python
async def test_mention_policy_accepts_media_event_without_textual_mention_marker() -> None:
    ...
```

**Step 2: Run to verify RED**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "mention_policy_accepts_media_event" -v`
Expected: FAIL.

**Step 3: Implement minimal policy-safe logic**

Do not drop media events solely due to missing textual mention marker.

**Step 4: Re-run mention policy subset**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "mention_policy" -v`
Expected: PASS.

**Step 5: Commit policy fix**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "fix(matrix): avoid false mention-policy drops for media events"
```

### Task 5 (Conditional): Add BadEvent fallback if diagnostics prove callback miss

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `tests/adapters/channels/test_matrix.py`

**Run only when logs show encrypted media bypassing both media callbacks.**

**Step 1: Add failing fallback test**

```python
async def test_bad_event_with_media_shape_routes_to_media_pipeline() -> None:
    ...
```

**Step 2: Verify RED**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -k "bad_event" -v`
Expected: FAIL.

**Step 3: Implement guarded fallback**

Only route media-shaped bad events (`msgtype` media + `content.file.url`).

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

**Step 6: Final commit (if needed)**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "fix(matrix): ensure encrypted inbound file uploads reach agent context"
```
