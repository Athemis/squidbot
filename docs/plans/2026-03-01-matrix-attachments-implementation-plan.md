# Matrix Attachment Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix Matrix outbound attachment upload, add safe inbound image multimodal support, and keep cross-channel attachment behavior compatible.

**Architecture:** Extend core message models for multimodal user content and multi-attachment outbound payloads. Update Matrix adapter for BytesIO upload and guarded image embedding, update Email adapter for list-attachment compatibility, and wire gateway dispatch in the real runtime loops (`cli/gateway.py`). Add lightweight debug logs at attachment decision points.

**Tech Stack:** Python 3.14, matrix-nio, OpenAI chat multimodal payload format, Loguru, pytest, mypy --strict, ruff

---

### Task 1: Add failing tests for model contract changes

**Files:**
- Modify: `tests/core/test_models.py`

**Step 1: Write the failing tests**

Add tests for:

```python
def test_message_to_openai_dict_multimodal_content() -> None:
    content = [
        {"type": "text", "text": "hello"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]
    msg = Message(role="user", content=content)
    assert msg.to_openai_dict()["content"] == content


def test_outbound_message_attachment_defaults_to_empty_list() -> None:
    session = Session(channel="matrix", sender_id="@u:matrix.org")
    msg = OutboundMessage(session=session, text="hi")
    assert msg.attachment == []


def test_inbound_message_multimodal_content_default_none() -> None:
    session = Session(channel="matrix", sender_id="@u:matrix.org")
    msg = InboundMessage(session=session, text="x")
    assert msg.multimodal_content is None
```

**Step 2: Run tests to confirm failures**

Run:
`uv run pytest tests/core/test_models.py -k "multimodal_content or attachment_defaults" -v`

Expected: FAIL (fields/types not yet updated).

**Step 3: Commit test-only red phase**

```bash
git add tests/core/test_models.py
git commit -m "test: add failing model contract tests for matrix attachment rework"
```

---

### Task 2: Implement core model changes

**Files:**
- Modify: `squidbot/core/models.py`
- Modify: `tests/core/test_models.py` (if minor fixture/type adjustments needed)

**Step 1: Implement minimal changes**

Update dataclasses:

```python
class Message:
    content: str | list[dict[str, Any]]


class InboundMessage:
    ...
    multimodal_content: list[dict[str, Any]] | None = None


class OutboundMessage:
    ...
    attachment: list[Path] = field(default_factory=list)
```

Keep `to_openai_dict()` behavior unchanged except typing compatibility.

**Step 2: Run focused tests**

Run:
`uv run pytest tests/core/test_models.py -v`

Expected: PASS.

**Step 3: Run strict checks**

Run:
`uv run mypy squidbot/core/models.py`

Expected: PASS.

**Step 4: Commit**

```bash
git add squidbot/core/models.py tests/core/test_models.py
git commit -m "feat: support multimodal inbound content and list-based attachments in models"
```

---

### Task 3: Update agent loop to accept multimodal user payloads

**Files:**
- Modify: `squidbot/core/agent.py`
- Modify: `tests/core/test_agent.py`

**Step 1: Write failing test**

Add a test asserting `AgentLoop.run()` can receive `user_message` as multimodal list and forwards it into the LLM message list as user content.

**Step 2: Run to verify failure**

Run:
`uv run pytest tests/core/test_agent.py -k "multimodal" -v`

Expected: FAIL.

**Step 3: Implement minimal fix**

- Change `run(..., user_message: str | list[dict[str, Any]], ...)`.
- Build memory context with a text fallback string when input is multimodal.
- Replace the last user message content with multimodal payload before LLM call.
- Persist text-only fallback in history (not base64 payload).

**Step 4: Re-run tests**

Run:
`uv run pytest tests/core/test_agent.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/core/agent.py tests/core/test_agent.py
git commit -m "feat: allow agent loop to handle multimodal user messages"
```

---

### Task 4: Add config defaults for safe inbound/outbound media handling

**Files:**
- Modify: `squidbot/config/schema.py`
- Modify: `tests/config/test_schema.py`

**Step 1: Write failing config tests**

Add tests in `tests/config/test_schema.py` for Matrix config defaults:

```python
def test_matrix_media_limits_defaults() -> None:
    s = Settings()
    assert s.channels.matrix.max_inbound_download_bytes == 50 * 1024 * 1024
    assert s.channels.matrix.max_inbound_embed_bytes == 2 * 1024 * 1024
    assert s.channels.matrix.max_outbound_upload_bytes == 20 * 1024 * 1024
```

**Step 2: Run to verify failure**

Run:
`uv run pytest tests/config/test_schema.py -k "matrix_media_limits_defaults" -v`

Expected: FAIL.

**Step 3: Implement schema fields**

In `MatrixChannelConfig` add:

```python
max_inbound_download_bytes: int = 50 * 1024 * 1024
max_inbound_embed_bytes: int = 2 * 1024 * 1024
max_outbound_upload_bytes: int = 20 * 1024 * 1024
```

**Step 4: Re-run tests**

Run:
`uv run pytest tests/config/test_schema.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/config/schema.py tests/config/test_schema.py
git commit -m "feat: add matrix inbound and outbound media size thresholds"
```

---

### Task 5: Fix Matrix outbound upload and add multiple attachment support

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `tests/adapters/channels/test_matrix.py`

**Step 1: Write failing tests**

Add tests:
- upload call receives `io.BytesIO` as first argument
- `send()` uploads each attachment in `message.attachment`
- when homeserver upload cap is available, effective limit uses `min(local, server)`
- file exceeding effective outbound limit is skipped

**Step 2: Run to verify failure**

Run:
`uv run pytest tests/adapters/channels/test_matrix.py -k "bytesio or multiple_attachments" -v`

Expected: FAIL.

**Step 3: Implement minimal changes**

- Add `import io`.
- Replace broken lambda upload argument with `io.BytesIO(data)`.
- Update `send()` to iterate `for path in message.attachment:`.
- Add helper that fetches/caches homeserver upload limit (`content_repository_config().upload_size`).
- Compute `effective_outbound_limit = min(max_outbound_upload_bytes, server_upload_limit)` when server limit exists.
- Skip uploads above effective limit and emit debug reason `exceeds_outbound_limit`.
- Preserve existing behavior: send text even if attachment send fails.

**Step 4: Re-run tests**

Run:
`uv run pytest tests/adapters/channels/test_matrix.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "fix(matrix): use BytesIO, server-aware upload limits, and multiple outbound attachments"
```

---

### Task 6: Add inbound embedding guardrails (allowlist + size gates)

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `tests/adapters/channels/test_matrix.py`

**Step 1: Write failing tests for guardrails**

Add tests for:
- jpeg/png/webp/gif under embed limit -> `multimodal_content` present
- svg -> no embedding (text-only fallback)
- declared size above download limit -> skip download and fallback text
- downloaded size above embed limit -> no embedding
- downloaded size above download limit -> discard payload + fallback text
- non-allowlist file (svg/pdf) under download limit -> still downloaded/persisted + text path marker, `multimodal_content is None`
- `_handle_media` propagation: when `_download_attachment` returns multimodal blocks, queued `InboundMessage.multimodal_content` matches exactly
- encoded-size boundary: payload just below encoded threshold embeds; just above threshold does not embed

**Step 2: Run to verify failure**

Run:
`uv run pytest tests/adapters/channels/test_matrix.py -k "embed or svg or download_limit" -v`

Expected: FAIL.

**Step 3: Implement minimal guardrails**

In `matrix.py`:
- Define `EMBEDDABLE_IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})`
- Check declared size first (if available) against `max_inbound_download_bytes`
- Only embed when MIME in allowlist and estimated encoded size <= `max_inbound_embed_bytes`
- Check downloaded byte length against `max_inbound_download_bytes` before persistence/embedding
- Non-allowlist files are still downloaded and persisted, then forwarded as text path

**Step 4: Re-run tests**

Run:
`uv run pytest tests/adapters/channels/test_matrix.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "feat(matrix): add inbound image embedding guardrails and MIME allowlist"
```

---

### Task 7: Preserve Email channel behavior with new attachment list contract

**Files:**
- Modify: `squidbot/adapters/channels/email.py`
- Modify: `tests/adapters/channels/test_email.py`

**Step 1: Write failing test**

Add test: when `OutboundMessage.attachment` contains two files, Email channel attaches both files to the outgoing MIME message.

**Step 2: Run to verify failure**

Run:
`uv run pytest tests/adapters/channels/test_email.py -k "multiple_attachments" -v`

Expected: FAIL.

**Step 3: Implement compatibility behavior**

In `email.py`:
- Replace single-path check with iteration over `message.attachment`.
- Build multipart/mixed once when at least one file exists.
- For each existing path, create one MIME part and attach it.

```python
attachments = [p for p in message.attachment if p.exists()]
if attachments:
    ...
    for attachment in attachments:
        ...
```

Keep MIME creation unchanged.

**Step 4: Re-run tests**

Run:
`uv run pytest tests/adapters/channels/test_email.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/adapters/channels/email.py tests/adapters/channels/test_email.py
git commit -m "feat(email): attach all files from list-based attachment contract"
```

---

### Task 8: Wire multimodal dispatch in the actual gateway runtime loops

**Files:**
- Modify: `squidbot/cli/gateway.py`
- Modify: `tests/adapters/test_channel_loops.py`

**Step 1: Write failing test**

Add a focused test for dispatch behavior: when `InboundMessage.multimodal_content` exists, gateway passes list payload to `loop.run()`; otherwise passes `inbound.text`.

**Step 2: Run to verify failure**

Run:
`uv run pytest tests/adapters/test_channel_loops.py -k "multimodal" -v`

Expected: FAIL.

**Step 3: Implement in both loops**

Update both call sites in `gateway.py`:
- `_channel_loop_with_state()`
- `_channel_loop()`

Change:

```python
inbound.text
```

to:

```python
inbound.multimodal_content if inbound.multimodal_content else inbound.text
```

**Step 4: Re-run tests**

Run:
`uv run pytest tests/adapters/test_channel_loops.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/cli/gateway.py tests
git commit -m "feat(gateway): forward multimodal inbound payloads to agent loop"
```

---

### Task 9: Add lightweight debug logging for observability

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `squidbot/cli/gateway.py`

**Step 1: Add debug logs at decision points**

Outbound (`matrix.py`):
- before upload: path, mime, size
- after upload: mxc URI
- after send: room + msgtype

Inbound (`matrix.py`):
- before download: mxc + filename
- after download: size + mime
- embedding decision: `embedded` vs `text_fallback` + reason (`non-image`, `exceeds_embed_limit`, `exceeds_download_limit_preflight`, `exceeds_download_limit_postfetch`)

Gateway (`gateway.py`):
- before `loop.run()`: session id + `multimodal=True/False`

Use brace-style logging only:

```python
logger.debug("Matrix inbound decision: mxc={} embedded={} reason={}", mxc, embedded, reason)
```

**Step 2: Run targeted tests**

Run:
`uv run pytest tests/adapters/channels/test_matrix.py tests/adapters/channels/test_email.py -v`

Expected: PASS.

**Step 3: Commit**

```bash
git add squidbot/adapters/channels/matrix.py squidbot/cli/gateway.py
git commit -m "feat(matrix): add debug logs for attachment flow decisions"
```

---

### Task 10: Full verification and PR

**Files:**
- Modify: none (verification + release task)

**Step 1: Run full test suite**

Run:
`uv run pytest -v --tb=short`

Expected: PASS.

**Step 2: Run type-checking**

Run:
`uv run mypy squidbot/`

Expected: PASS.

**Step 3: Run lint + format check**

Run:
`uv run ruff check . && uv run ruff format . --check`

Expected: PASS.

**Step 4: Optional runtime smoke check with debug logs**

Run gateway with debug enabled and send one image + one non-image over Matrix:

`LOG_LEVEL=DEBUG uv run squidbot gateway`

Expected: debug lines show upload/download decisions and multimodal dispatch flag.

**Step 5: Create branch, push, PR**

```bash
git checkout -b feat/matrix-attachment-multimodal
git push -u origin feat/matrix-attachment-multimodal
gh pr create --title "feat(matrix): fix attachment upload and add safe inbound multimodal images" --body "$(cat <<'EOF'
## Summary

- fix matrix outbound upload by using `io.BytesIO`
- support multiple outbound attachments in Matrix
- respect homeserver-advertised upload cap (`m.upload.size`) with local threshold
- add safe inbound image embedding with MIME allowlist and size guardrails
- forward multimodal inbound payloads via `cli/gateway.py`
- attach all files in Email for list-based attachment contract
- add lightweight debug logs for attachment decisions

## Docs

- `docs/plans/2026-03-01-matrix-attachments-design.md`
- `docs/plans/2026-03-01-matrix-attachments-implementation-plan.md`
EOF
)"
```
