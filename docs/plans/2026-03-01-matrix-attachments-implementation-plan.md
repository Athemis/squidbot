# Matrix Attachment Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix Matrix outbound attachment upload bug and add inbound multimodal image support for vision LLMs.

**Architecture:** `Message.content` becomes `str | list[dict]`; `OutboundMessage.attachment` becomes `list[Path]`; Matrix channel embeds downloaded images as Base64 `image_url` blocks; outbound upload uses `io.BytesIO` instead of a broken lambda.

**Tech Stack:** matrix-nio, Python `io.BytesIO`, `base64` stdlib, OpenAI multimodal message format, pytest + unittest.mock

---

### Task 1: Extend `Message.content` and `OutboundMessage.attachment` in models.py

**Files:**
- Modify: `squidbot/core/models.py`
- Test: `tests/core/test_models.py`

**Step 1: Write the failing test**

In `tests/core/test_models.py`, add:

```python
def test_message_to_openai_dict_multimodal_content() -> None:
    """Message with list content serializes correctly for OpenAI API."""
    content: list[dict[str, Any]] = [
        {"type": "text", "text": "hello"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
    ]
    msg = Message(role="user", content=content)
    d = msg.to_openai_dict()
    assert d["content"] == content


def test_outbound_message_attachment_defaults_to_empty_list() -> None:
    """OutboundMessage.attachment is [] by default."""
    session = Session(channel="test", sender_id="u1")
    msg = OutboundMessage(session=session, text="hi")
    assert msg.attachment == []


def test_outbound_message_attachment_accepts_list() -> None:
    """OutboundMessage.attachment accepts a list of Path objects."""
    session = Session(channel="test", sender_id="u1")
    paths = [Path("/tmp/a.jpg"), Path("/tmp/b.pdf")]
    msg = OutboundMessage(session=session, text="hi", attachment=paths)
    assert msg.attachment == paths
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_models.py::test_message_to_openai_dict_multimodal_content tests/core/test_models.py::test_outbound_message_attachment_defaults_to_empty_list tests/core/test_models.py::test_outbound_message_attachment_accepts_list -v
```

Expected: FAIL (type annotation mismatch, default wrong)

**Step 3: Modify `squidbot/core/models.py`**

Change `Message.content`:
```python
# Before:
content: str
# After:
content: str | list[dict[str, Any]]
```

Change `OutboundMessage.attachment`:
```python
# Before:
attachment: Path | None = None
# After:
attachment: list[Path] = field(default_factory=list)
```

Remove the `Path` import if no longer used elsewhere (check first — `Path` may still be used in other fields). Add `field` import if missing from `dataclasses`.

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/core/test_models.py -v
```

**Step 5: Run mypy and ruff**

```bash
uv run mypy squidbot/core/models.py
uv run ruff check squidbot/core/models.py
```

Fix any type errors. The `Message.content` change may require updating `to_openai_dict()` — check that `d["content"] = self.content` still works (it does; dict serializes correctly).

**Step 6: Commit**

```bash
git add squidbot/core/models.py tests/core/test_models.py
git commit -m "feat: extend Message.content to support multimodal list and OutboundMessage.attachment to list"
```

---

### Task 2: Update `InboundMessage` with optional `multimodal_content` field

**Files:**
- Modify: `squidbot/core/models.py`
- Test: `tests/core/test_models.py`

**Step 1: Write the failing test**

```python
def test_inbound_message_multimodal_content_default_none() -> None:
    """InboundMessage.multimodal_content defaults to None."""
    session = Session(channel="matrix", sender_id="@user:matrix.org")
    msg = InboundMessage(session=session, text="[Anhang: foo.jpg]")
    assert msg.multimodal_content is None


def test_inbound_message_multimodal_content_set() -> None:
    """InboundMessage.multimodal_content can be set to a list."""
    session = Session(channel="matrix", sender_id="@user:matrix.org")
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": "[Anhang: foo.jpg]"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,xyz"}},
    ]
    msg = InboundMessage(session=session, text="[Anhang: foo.jpg]", multimodal_content=blocks)
    assert msg.multimodal_content == blocks
```

**Step 2: Run to verify FAIL**

```bash
uv run pytest tests/core/test_models.py::test_inbound_message_multimodal_content_default_none tests/core/test_models.py::test_inbound_message_multimodal_content_set -v
```

**Step 3: Add field to `InboundMessage`**

```python
@dataclass
class InboundMessage:
    """A message received from a channel."""
    session: Session
    text: str
    received_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    multimodal_content: list[dict[str, Any]] | None = None  # ← add this
```

**Step 4: Run tests to verify PASS**

```bash
uv run pytest tests/core/test_models.py -v
```

**Step 5: Commit**

```bash
git add squidbot/core/models.py tests/core/test_models.py
git commit -m "feat: add multimodal_content field to InboundMessage"
```

---

### Task 3: Update `AgentLoop.run()` to pass multimodal content to LLM

**Files:**
- Modify: `squidbot/core/agent.py`
- Test: `tests/core/test_agent.py`

**Step 1: Read existing agent tests to understand the test double pattern**

Read `tests/core/test_agent.py` to understand `ScriptedLLM` and `CollectingChannel`.

**Step 2: Write a failing test**

Add to `tests/core/test_agent.py`:

```python
async def test_multimodal_user_message_sent_to_llm() -> None:
    """AgentLoop passes multimodal content list as Message.content to LLM."""
    # ScriptedLLM records what messages it received
    captured: list[list[Message]] = []

    class CapturingLLM:
        async def chat(
            self,
            messages: list[Message],
            tools: list[ToolDefinition],
            *,
            stream: bool = True,
        ) -> AsyncIterator[str | list[ToolCall] | tuple[list[ToolCall], str | None]]:
            captured.append(messages)
            async def _gen() -> AsyncIterator[str | list[ToolCall] | tuple[list[ToolCall], str | None]]:
                yield "ok"
            return _gen()

    # Build a minimal agent
    memory = InMemoryMemory()  # use existing test double
    registry = ToolRegistry()
    agent = AgentLoop(CapturingLLM(), MemoryManager(memory), registry, "system")
    channel = CollectingChannel()

    multimodal: list[dict[str, Any]] = [
        {"type": "text", "text": "what is in this image?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]
    await agent.run(
        session=Session(channel="matrix", sender_id="@user:matrix.org"),
        user_message=multimodal,
        channel=channel,
    )

    # Find the user message in captured
    user_msgs = [m for m in captured[0] if m.role == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0].content == multimodal
```

**Step 3: Run to verify FAIL**

```bash
uv run pytest tests/core/test_agent.py::test_multimodal_user_message_sent_to_llm -v
```

**Step 4: Update `agent.run()` signature**

In `squidbot/core/agent.py`:

```python
async def run(
    self,
    session: Session,
    user_message: str | list[dict[str, Any]],  # ← change from str
    channel: ChannelPort,
    *,
    llm: LLMPort | None = None,
    extra_tools: Sequence[ToolPort] | None = None,
    outbound_metadata: dict[str, Any] | None = None,
) -> None:
```

In `_memory.build_messages()` the `user_message` is a str. When multimodal, we need to extract the text portion for memory storage. Update the call:

```python
# Extract text for memory (multimodal → use first text block or repr)
user_text_for_memory: str
if isinstance(user_message, str):
    user_text_for_memory = user_message
else:
    text_blocks = [b["text"] for b in user_message if b.get("type") == "text"]
    user_text_for_memory = " ".join(text_blocks) if text_blocks else "[multimodal message]"

try:
    messages = await self._memory.build_messages(
        user_message=user_text_for_memory,
        system_prompt=self._system_prompt,
    )
except Exception as exc:
    ...

# Replace the last user message content with multimodal if needed
if isinstance(user_message, list) and messages:
    last_user = messages[-1]
    if last_user.role == "user":
        messages[-1] = Message(
            role="user",
            content=user_message,
            timestamp=last_user.timestamp,
            channel=last_user.channel,
            sender_id=last_user.sender_id,
        )
```

Also update `persist_exchange`:
```python
await self._memory.persist_exchange(
    channel=session.channel,
    sender_id=session.sender_id,
    user_message=user_text_for_memory,  # ← use text-only for storage
    assistant_reply=final_text,
)
```

**Step 5: Run tests to verify PASS**

```bash
uv run pytest tests/core/test_agent.py -v
uv run mypy squidbot/core/agent.py
```

**Step 6: Commit**

```bash
git add squidbot/core/agent.py tests/core/test_agent.py
git commit -m "feat: agent.run() accepts multimodal list as user_message"
```

---

### Task 4: Fix Matrix outbound upload bug

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Test: `tests/adapters/channels/test_matrix.py`

**Step 1: Read existing matrix tests**

Read `tests/adapters/channels/test_matrix.py` to understand existing mock structure.

**Step 2: Write failing test for upload**

```python
async def test_send_attachment_uses_bytesio(tmp_path: Path) -> None:
    """_send_attachment passes BytesIO to client.upload(), not a lambda."""
    import io
    from unittest.mock import AsyncMock, MagicMock, patch

    test_file = tmp_path / "test.jpg"
    test_file.write_bytes(b"fake-jpeg-data")

    mock_client = AsyncMock()
    mock_upload_response = MagicMock()
    mock_upload_response.content_uri = "mxc://matrix.org/abc123"
    mock_client.upload = AsyncMock(return_value=(mock_upload_response, None))
    mock_client.room_send = AsyncMock(return_value=MagicMock(spec=[]))  # not RoomSendError

    config = MatrixChannelConfig(
        enabled=True,
        homeserver="https://matrix.org",
        user_id="@bot:matrix.org",
        access_token="tok",
    )
    channel = MatrixChannel(config)
    channel._client = mock_client

    await channel._send_attachment("!room:matrix.org", test_file, None)

    # Assert upload was called with BytesIO, not a lambda
    call_args = mock_client.upload.call_args
    first_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("data_provider")
    assert isinstance(first_arg, io.BytesIO), f"Expected BytesIO, got {type(first_arg)}"
```

**Step 3: Run to verify FAIL**

```bash
uv run pytest tests/adapters/channels/test_matrix.py::test_send_attachment_uses_bytesio -v
```

Expected: FAIL (currently uses lambda)

**Step 4: Fix `_send_attachment()` in `matrix.py`**

Change lines 577-583:
```python
# Before:
data = await asyncio.to_thread(path.read_bytes)
resp = await self._client.upload(
    data_provider=lambda *_: data,
    content_type=mime,
    filename=path.name,
    filesize=len(data),
)

# After:
import io  # add to top-of-file imports (stdlib)
data = await asyncio.to_thread(path.read_bytes)
resp = await self._client.upload(
    io.BytesIO(data),
    content_type=mime,
    filename=path.name,
    filesize=len(data),
)
```

Add `import io` to the top-level imports in `matrix.py` (keep with stdlib block).

**Step 5: Run tests to verify PASS**

```bash
uv run pytest tests/adapters/channels/test_matrix.py -v
uv run mypy squidbot/adapters/channels/matrix.py
```

**Step 6: Commit**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "fix: matrix upload uses io.BytesIO instead of broken lambda data_provider"
```

---

### Task 5: Support multiple outbound attachments in Matrix channel

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `squidbot/adapters/channels/cli.py` (check for `attachment` references)
- Modify: `squidbot/adapters/channels/email.py` (check for `attachment` references)
- Test: `tests/adapters/channels/test_matrix.py`

**Step 1: Check all attachment references**

Search for `message.attachment` or `.attachment` across channel adapters:
```bash
uv run rg "\.attachment" squidbot/adapters/channels/
```

**Step 2: Write failing test for multiple attachments**

```python
async def test_send_multiple_attachments(tmp_path: Path) -> None:
    """send() uploads and sends each attachment as a separate Matrix media event."""
    file1 = tmp_path / "a.jpg"
    file2 = tmp_path / "b.png"
    file1.write_bytes(b"jpeg")
    file2.write_bytes(b"png")

    mock_client = AsyncMock()
    upload_resp = MagicMock()
    upload_resp.content_uri = "mxc://matrix.org/xyz"
    mock_client.upload = AsyncMock(return_value=(upload_resp, None))
    mock_client.room_send = AsyncMock(return_value=MagicMock(spec=[]))

    config = MatrixChannelConfig(enabled=True, homeserver="https://matrix.org",
                                  user_id="@bot:matrix.org", access_token="tok")
    channel = MatrixChannel(config)
    channel._client = mock_client

    session = Session(channel="matrix", sender_id="@user:matrix.org")
    msg = OutboundMessage(
        session=session,
        text="here are two images",
        attachment=[file1, file2],
        metadata={"matrix_room_id": "!room:matrix.org"},
    )
    await channel.send(msg)

    assert mock_client.upload.call_count == 2
```

**Step 3: Run to verify FAIL**

```bash
uv run pytest tests/adapters/channels/test_matrix.py::test_send_multiple_attachments -v
```

**Step 4: Update `MatrixChannel.send()` to iterate attachment list**

```python
async def send(self, message: OutboundMessage) -> None:
    """Send a message (and optional attachments) to Matrix."""
    assert self._client is not None
    room_id = message.metadata.get("matrix_room_id", "")
    if not isinstance(room_id, str) or not room_id:
        logger.warning("MatrixChannel.send: no matrix_room_id in metadata, dropping")
        return

    thread_root_raw = message.metadata.get("matrix_thread_root")
    thread_root: str | None = thread_root_raw if isinstance(thread_root_raw, str) else None

    # Send each attachment
    for attachment_path in message.attachment:
        if attachment_path.exists():
            await self._send_attachment(room_id, attachment_path, thread_root)

    # Send text (skip if empty and attachments were sent)
    if message.text or not message.attachment:
        await self._send_text(room_id, message.text, thread_root)
```

Also update CLI and Email channels: if they accessed `message.attachment` as `Path | None`, update to handle `list[Path]`. Likely they ignore it — confirm and add a `# attachment field ignored` comment.

**Step 5: Run all tests**

```bash
uv run pytest tests/ -v
uv run mypy squidbot/adapters/channels/
```

**Step 6: Commit**

```bash
git add squidbot/adapters/channels/matrix.py squidbot/adapters/channels/cli.py squidbot/adapters/channels/email.py tests/adapters/channels/test_matrix.py
git commit -m "feat: matrix channel sends multiple attachments per outbound message"
```

---

### Task 6: Add size limit config to MatrixChannelConfig

**Files:**
- Modify: `squidbot/config/schema.py`
- Test: `tests/test_config.py` (or wherever config tests live)

**Step 1: Write failing test**

```python
def test_matrix_channel_config_defaults() -> None:
    """MatrixChannelConfig has a max_inbound_media_bytes field defaulting to 10MB."""
    config = MatrixChannelConfig()
    assert config.max_inbound_media_bytes == 10 * 1024 * 1024  # 10 MB
```

**Step 2: Run to verify FAIL**

```bash
uv run pytest tests/ -k "matrix_channel_config_defaults" -v
```

**Step 3: Add field**

```python
class MatrixChannelConfig(BaseModel):
    """Configuration for the Matrix channel adapter."""
    enabled: bool = False
    homeserver: str = "https://matrix.org"
    user_id: str = ""
    access_token: str = ""
    device_id: str = "SQUIDBOT01"
    room_ids: list[str] = Field(default_factory=list)
    group_policy: str = "mention"
    allowlist: list[str] = Field(default_factory=list)
    max_inbound_media_bytes: int = 10 * 1024 * 1024  # ← add this (10 MB)
```

**Step 4: Run tests**

```bash
uv run pytest tests/ -v
```

**Step 5: Commit**

```bash
git add squidbot/config/schema.py
git commit -m "feat: add max_inbound_media_bytes to MatrixChannelConfig (default 10MB)"
```

---

### Task 7: Add inbound image-to-multimodal conversion in Matrix channel

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Test: `tests/adapters/channels/test_matrix.py`

**Step 1: Write failing test for image multimodal conversion**

```python
async def test_download_attachment_image_returns_multimodal(tmp_path: Path) -> None:
    """_download_attachment returns multimodal_content for images."""
    import base64
    fake_jpeg = b"\\xff\\xd8\\xff" + b"x" * 100  # fake JPEG header

    mock_client = AsyncMock()
    mock_download = MagicMock()
    mock_download.body = fake_jpeg
    mock_download.content_type = "image/jpeg"
    mock_client.download = AsyncMock(return_value=mock_download)

    config = MatrixChannelConfig(enabled=True, homeserver="https://matrix.org",
                                  user_id="@bot:matrix.org", access_token="tok",
                                  max_inbound_media_bytes=10 * 1024 * 1024)
    channel = MatrixChannel(config)
    channel._client = mock_client

    # Create a fake event
    event = MagicMock()
    event.url = "mxc://matrix.org/fakemediaid"
    event.file = None
    event.body = "photo.jpg"
    event.info = MagicMock()
    event.info.mimetype = "image/jpeg"

    text, multimodal = await channel._download_attachment(event)

    assert "photo.jpg" in text
    assert multimodal is not None
    assert len(multimodal) == 2
    assert multimodal[0]["type"] == "text"
    assert multimodal[1]["type"] == "image_url"
    assert multimodal[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    # Verify base64 content is correct
    expected_b64 = base64.b64encode(fake_jpeg).decode("ascii")
    assert expected_b64 in multimodal[1]["image_url"]["url"]


async def test_download_attachment_non_image_returns_no_multimodal() -> None:
    """_download_attachment returns None multimodal_content for non-image files."""
    fake_pdf = b"%PDF-1.4" + b"x" * 100

    mock_client = AsyncMock()
    mock_download = MagicMock()
    mock_download.body = fake_pdf
    mock_download.content_type = "application/pdf"
    mock_client.download = AsyncMock(return_value=mock_download)

    config = MatrixChannelConfig(enabled=True, homeserver="https://matrix.org",
                                  user_id="@bot:matrix.org", access_token="tok")
    channel = MatrixChannel(config)
    channel._client = mock_client

    event = MagicMock()
    event.url = "mxc://matrix.org/fakemediaid"
    event.file = None
    event.body = "document.pdf"
    event.info = MagicMock()
    event.info.mimetype = "application/pdf"

    text, multimodal = await channel._download_attachment(event)

    assert "document.pdf" in text
    assert multimodal is None


async def test_download_attachment_image_too_large_returns_no_multimodal() -> None:
    """Images exceeding max_inbound_media_bytes get text-path only, no Base64."""
    # 1 byte over limit
    small_limit = 10
    fake_jpeg = b"\\xff\\xd8" + b"x" * small_limit  # 12 bytes > 10 limit

    mock_client = AsyncMock()
    mock_download = MagicMock()
    mock_download.body = fake_jpeg
    mock_download.content_type = "image/jpeg"
    mock_client.download = AsyncMock(return_value=mock_download)

    config = MatrixChannelConfig(enabled=True, homeserver="https://matrix.org",
                                  user_id="@bot:matrix.org", access_token="tok",
                                  max_inbound_media_bytes=small_limit)
    channel = MatrixChannel(config)
    channel._client = mock_client

    event = MagicMock()
    event.url = "mxc://matrix.org/fakemediaid"
    event.file = None
    event.body = "big_photo.jpg"
    event.info = MagicMock()
    event.info.mimetype = "image/jpeg"

    text, multimodal = await channel._download_attachment(event)

    assert "big_photo.jpg" in text
    assert multimodal is None
```

**Step 2: Run to verify FAIL**

```bash
uv run pytest tests/adapters/channels/test_matrix.py::test_download_attachment_image_returns_multimodal tests/adapters/channels/test_matrix.py::test_download_attachment_non_image_returns_no_multimodal tests/adapters/channels/test_matrix.py::test_download_attachment_image_too_large_returns_no_multimodal -v
```

**Step 3: Refactor `_download_attachment()` to return `(str, list[dict] | None)`**

The current signature is:
```python
async def _download_attachment(self, event: Any) -> str:
```

Change to:
```python
async def _download_attachment(self, event: Any) -> tuple[str, list[dict[str, Any]] | None]:
```

Add `import base64` to stdlib imports at the top of `matrix.py`.

New implementation logic (after saving to tmp_path):

```python
# Build text description (always)
text = f"[Anhang: {filename} ({mimetype})] → {tmp_path}"

# Build multimodal image block if MIME is an image and size within limit
multimodal: list[dict[str, Any]] | None = None
if mimetype.startswith("image/") and len(body) <= self._config.max_inbound_media_bytes:
    try:
        b64 = base64.b64encode(body).decode("ascii")
        multimodal = [
            {"type": "text", "text": text},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mimetype};base64,{b64}"},
            },
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("MatrixChannel: base64 encoding failed: {}", exc)

return text, multimodal
```

**Step 4: Update `_handle_media()` to use the new return value**

```python
async def _handle_media(self, room: Any, event: Any) -> None:
    """Handle an incoming m.room.message with a media msgtype."""
    if not self._accept_event(room, event):
        return
    assert self._client is not None
    try:
        text, multimodal_content = await self._download_attachment(event)
    except Exception as exc:  # noqa: BLE001
        text = f"[Anhang nicht verfügbar: {exc}]"
        multimodal_content = None
    metadata = self._extract_metadata(event)
    session = Session(channel="matrix", sender_id=event.sender)
    room_id: str = getattr(event, "room_id", getattr(room, "room_id", ""))
    self._session_rooms[session.id] = room_id
    self._queue.put_nowait(
        InboundMessage(
            session=session,
            text=text,
            metadata=metadata,
            multimodal_content=multimodal_content,
        )
    )
```

**Step 5: Run all tests**

```bash
uv run pytest tests/ -v
uv run mypy squidbot/adapters/channels/matrix.py
```

**Step 6: Commit**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "feat: matrix inbound images embedded as Base64 multimodal blocks"
```

---

### Task 8: Wire multimodal_content through gateway → agent.run()

**Files:**
- Modify: `squidbot/cli/main.py` (gateway message handling loop)
- Test: Integration check via existing gateway tests if any

**Step 1: Find where `InboundMessage` is consumed and `agent.run()` is called**

```bash
uv run rg "agent.run\|inbound\.text\|msg\.text" squidbot/cli/main.py squidbot/core/
```

Read the relevant section of `squidbot/cli/main.py` to understand the dispatch loop.

**Step 2: Update dispatch to pass `multimodal_content or text`**

Find the `agent.run()` call in the gateway loop. Change:

```python
# Before:
await agent.run(
    session=msg.session,
    user_message=msg.text,
    channel=channel,
    outbound_metadata=outbound_metadata,
)

# After:
await agent.run(
    session=msg.session,
    user_message=msg.multimodal_content if msg.multimodal_content else msg.text,
    channel=channel,
    outbound_metadata=outbound_metadata,
)
```

**Step 3: Run full test suite + mypy + ruff**

```bash
uv run pytest tests/ -v
uv run mypy squidbot/
uv run ruff check .
uv run ruff format . --check
```

Fix any issues.

**Step 4: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "feat: gateway passes multimodal_content to agent when present"
```

---

### Task 9: Final integration check + PR

**Step 1: Run full test suite**

```bash
uv run pytest tests/ -v --tb=short
```

All tests must pass.

**Step 2: Run mypy on entire package**

```bash
uv run mypy squidbot/
```

No errors allowed.

**Step 3: Run ruff**

```bash
uv run ruff check .
uv run ruff format . --check
```

**Step 4: Create PR**

```bash
git push -u origin matrix-attachment-support
gh pr create --title "feat: fix Matrix attachment upload bug and add inbound multimodal image support" \
  --body "$(cat <<'EOF'
## Summary

- Fix outbound attachment upload: use `io.BytesIO` instead of broken lambda `data_provider`
- Support multiple outbound attachments (`OutboundMessage.attachment: list[Path]`)
- Add inbound multimodal support: images from Matrix are Base64-encoded and embedded as `image_url` blocks in the user message context, enabling vision LLMs to directly see the image
- Non-image attachments (PDF, audio, video) continue to use text file-path approach
- Add `max_inbound_media_bytes` config (default 10MB) to control Base64 embedding size limit
- `Message.content` extended to `str | list[dict[str, Any]]` for OpenAI multimodal format
- `InboundMessage` gets optional `multimodal_content` field

## Reference

Design: `docs/plans/2026-03-01-matrix-attachments-design.md`
Reference implementation: Athemis/nanobot-redux `nanobot/channels/matrix.py`
EOF
)"
```
