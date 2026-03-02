# Performance Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate 14 identified bottlenecks — in-memory history cache, parallel I/O,
caching of long-lived objects, correctness fix for blocking I/O in the event loop.

**Architecture:** Hexagonal architecture remains intact. Changes in `core/` are limited to
MemoryManager and AgentLoop. Adapter optimizations are adapter-internal. No protocol changes.

**Tech Stack:** Python 3.14, asyncio, fcntl, Rich, aiosmtplib, openai SDK, uv/pytest/mypy

---

## Task 1: Write design document and implementation plan

**Files:**
- Create: `docs/plans/2026-03-02-performance-optimization-design.md`
- Create: `docs/plans/2026-03-02-performance-optimization-plan.md`

**Step 1:** Write the design document from the approved brainstorming output into
`docs/plans/2026-03-02-performance-optimization-design.md`.

**Step 2:** Write this file into
`docs/plans/2026-03-02-performance-optimization-plan.md`.

**Step 3:** Commit:
```bash
git add docs/plans/
git commit -m "docs(plans): add performance optimization design and implementation plan"
```

---

## Task 2: P0 Bug — heartbeat blocking I/O

**Files:**
- Modify: `squidbot/core/heartbeat.py`
- Test: `tests/core/test_heartbeat.py`

**Step 1: Write the failing test**

Add a new test to `tests/core/test_heartbeat.py`:

```python
async def test_read_heartbeat_file_uses_to_thread(tmp_path: Path) -> None:
    """_read_heartbeat_file must not block the event loop with synchronous I/O."""
    from unittest.mock import patch
    from squidbot.core.heartbeat import HeartbeatService

    hb_path = tmp_path / "HEARTBEAT.md"
    hb_path.write_text("hello", encoding="utf-8")

    service = HeartbeatService.__new__(HeartbeatService)
    service._workspace = tmp_path

    called_in_thread = False

    async def fake_to_thread(fn, *args, **kwargs):
        nonlocal called_in_thread
        called_in_thread = True
        return fn(*args, **kwargs)

    with patch("squidbot.core.heartbeat.asyncio.to_thread", side_effect=fake_to_thread):
        result = await service._read_heartbeat_file()

    assert called_in_thread, "_read_heartbeat_file must use asyncio.to_thread"
    assert result == "hello"
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/core/test_heartbeat.py::test_read_heartbeat_file_uses_to_thread -v
```
Expected: FAIL — `_read_heartbeat_file` is not `async def`.

**Step 3: Implement — `squidbot/core/heartbeat.py`**

Change `_read_heartbeat_file` from `def` to `async def`:
```python
async def _read_heartbeat_file(self) -> str | None:
    """Read HEARTBEAT.md from the workspace via asyncio.to_thread."""
    path = self._workspace / "HEARTBEAT.md"

    def _read() -> str | None:
        try:
            return path.read_text(encoding="utf-8") if path.exists() else None
        except Exception:
            return None

    return await asyncio.to_thread(_read)
```

In `_tick`, update the call to `await`:
```python
content = await self._read_heartbeat_file()
```

**Step 4: Run test to verify it passes**
```bash
uv run pytest tests/core/test_heartbeat.py -v
```

**Step 5: Lint and type-check**
```bash
uv run ruff check squidbot/core/heartbeat.py
uv run mypy squidbot/core/heartbeat.py
```

**Step 6: Commit**
```bash
git add squidbot/core/heartbeat.py tests/core/test_heartbeat.py
git commit -m "fix(heartbeat): use asyncio.to_thread for HEARTBEAT.md read"
```

---

## Task 3: JsonlMemory — move mkdir to `__init__`, clean up path helpers

**Files:**
- Modify: `squidbot/adapters/persistence/jsonl.py`
- Test: `tests/adapters/persistence/test_jsonl.py`

**Step 1: Write the failing test**

```python
async def test_no_mkdir_after_init(tmp_path: Path) -> None:
    """mkdir must not be called after __init__ completes."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.core.models import Message

    mkdir_calls: list[Path] = []
    original_mkdir = Path.mkdir

    def tracking_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        mkdir_calls.append(self)
        original_mkdir(self, *args, **kwargs)  # type: ignore[arg-type]

    mem = JsonlMemory(base_dir=tmp_path / "store")  # __init__ may call mkdir
    mkdir_calls.clear()  # reset after __init__

    with patch.object(Path, "mkdir", tracking_mkdir):
        await mem.load_history(last_n=10)
        await mem.append_message(
            Message(role="user", content="hi", channel="cli", sender_id="x")
        )

    assert mkdir_calls == [], f"mkdir called after __init__: {mkdir_calls}"
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/adapters/persistence/test_jsonl.py::test_no_mkdir_after_init -v
```

**Step 3: Implement**

Extend `JsonlMemory.__init__`:
```python
def __init__(self, base_dir: Path) -> None:
    self._base = base_dir
    # Create full directory structure once at startup
    self._base.mkdir(parents=True, exist_ok=True)
    (self._base / "workspace").mkdir(parents=True, exist_ok=True)
    (self._base / "cron").mkdir(parents=True, exist_ok=True)
```

Remove `mkdir` calls from `_history_file`, `_global_memory_file`, and `_cron_file`:
```python
def _history_file(base_dir: Path) -> Path:
    """Return the global history JSONL path."""
    return base_dir / "history.jsonl"


def _global_memory_file(base_dir: Path, *, write: bool = False) -> Path:
    """Return the global MEMORY.md path."""
    return base_dir / "workspace" / "MEMORY.md"


def _cron_file(base_dir: Path) -> Path:
    """Return the cron jobs JSON path."""
    return base_dir / "cron" / "jobs.json"
```

Keep `mkdir` in `_atomic_write_text` as a safety net (it is called by
`save_global_memory` and must remain robust against external deletions).

**Step 4: Run tests to verify they pass**
```bash
uv run pytest tests/adapters/persistence/test_jsonl.py -v
```

**Step 5: Lint, type-check, full suite**
```bash
uv run ruff check squidbot/adapters/persistence/jsonl.py
uv run mypy squidbot/adapters/persistence/
uv run pytest
```

**Step 6: Commit**
```bash
git add squidbot/adapters/persistence/jsonl.py tests/adapters/persistence/test_jsonl.py
git commit -m "perf(persistence): move mkdir to JsonlMemory.__init__"
```

---

## Task 4: asyncio.gather in MemoryManager.build_messages

**Files:**
- Modify: `squidbot/core/memory.py`
- Test: `tests/core/test_memory.py`

**Step 1: Write the failing test**

```python
async def test_build_messages_loads_history_and_memory_in_parallel() -> None:
    """load_history and load_global_memory must start before either completes."""
    import asyncio
    import time

    start_times: dict[str, float] = {}

    class TrackingStorage:
        async def load_history(self, last_n: int | None = None) -> list[Message]:
            start_times["history"] = time.monotonic()
            await asyncio.sleep(0.05)
            return []

        async def load_global_memory(self) -> str:
            start_times["memory"] = time.monotonic()
            await asyncio.sleep(0.05)
            return ""

        async def append_message(self, message: Message) -> None: ...
        async def save_global_memory(self, content: str) -> None: ...
        async def load_cron_jobs(self) -> list: return []  # type: ignore[return-value]
        async def save_cron_jobs(self, jobs: list) -> None: ...

    manager = MemoryManager(storage=TrackingStorage())  # type: ignore[arg-type]
    await manager.build_messages(user_message="hi", system_prompt="sys")

    assert "history" in start_times and "memory" in start_times
    # With sequential execution the gap between start times is ~50ms (one sleep).
    # With parallel execution both start within a few ms of each other.
    delta = abs(start_times["history"] - start_times["memory"])
    assert delta < 0.01, (
        f"load_history and load_global_memory started {delta*1000:.1f}ms apart — "
        "they are running sequentially, not in parallel"
    )
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/core/test_memory.py::test_build_messages_loads_history_and_memory_in_parallel -v
```

**Step 3: Implement**

Add `import asyncio` to `squidbot/core/memory.py` and update `build_messages`:
```python
history, global_memory = await asyncio.gather(
    self._storage.load_history(last_n=self._history_context_messages),
    self._storage.load_global_memory(),
)
```

**Step 4: Run tests to verify they pass**
```bash
uv run pytest tests/core/test_memory.py -v
```

**Step 5: Lint and type-check**
```bash
uv run ruff check squidbot/core/memory.py
uv run mypy squidbot/core/memory.py
```

**Step 6: Commit**
```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "perf(memory): load history and global memory in parallel with asyncio.gather"
```

---

## Task 5: Skills-XML cache in MemoryManager

**Files:**
- Modify: `squidbot/core/memory.py`
- Test: `tests/core/test_memory.py`

**Step 1: Write the failing test**

```python
async def test_skills_xml_cached_between_calls() -> None:
    """build_skills_xml is called only once when the skill list is unchanged."""
    from unittest.mock import patch
    from squidbot.core.skills import SkillMetadata

    skill = SkillMetadata(
        name="test_skill", description="desc", location="/f.md",
        always=False, available=True,
    )

    class FakeSkills:
        def list_skills(self) -> list[SkillMetadata]:
            return [skill]

        def load_skill_body(self, name: str) -> str:
            return "body"

    class MinimalStorage:
        async def load_history(self, last_n: int | None = None) -> list[Message]:
            return []

        async def load_global_memory(self) -> str:
            return ""

        async def append_message(self, m: Message) -> None: ...
        async def save_global_memory(self, c: str) -> None: ...
        async def load_cron_jobs(self) -> list: return []  # type: ignore[return-value]
        async def save_cron_jobs(self, j: list) -> None: ...

    manager = MemoryManager(
        storage=MinimalStorage(),  # type: ignore[arg-type]
        skills=FakeSkills(),  # type: ignore[arg-type]
    )

    build_calls: list[int] = []

    def counting_build(skills):  # type: ignore[no-untyped-def]
        build_calls.append(1)
        return "<skills/>"

    with patch("squidbot.core.memory.build_skills_xml", side_effect=counting_build):
        await manager.build_messages("hi", "sys")
        await manager.build_messages("hi again", "sys")

    assert len(build_calls) == 1, f"build_skills_xml called {len(build_calls)} times"
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/core/test_memory.py::test_skills_xml_cached_between_calls -v
```

**Step 3: Implement**

Add cache field to `MemoryManager.__init__`:
```python
# Cache for the assembled skills block.
# Key: frozenset of (name, location_str, available, always) tuples.
# Value: the assembled XML + always-skill bodies string.
self._skills_cache: tuple[frozenset[tuple[str, str, bool, bool]], str] | None = None
```

Replace the skills block in `build_messages` with cached logic and list-join for
the full system prompt. `always` must be part of the fingerprint because it controls
which skill bodies are embedded in the cached string:
```python
system_parts: list[str] = [system_prompt]
if global_memory.strip():
    system_parts.append(f"## Your Memory\n\n{global_memory}")

if self._skills is not None:
    from squidbot.core.skills import build_skills_xml  # noqa: PLC0415

    skill_list = self._skills.list_skills()
    fingerprint = frozenset(
        (s.name, str(s.location), s.available, s.always) for s in skill_list
    )

    if self._skills_cache is None or self._skills_cache[0] != fingerprint:
        parts: list[str] = [build_skills_xml(skill_list)]
        for skill in skill_list:
            if skill.always and skill.available:
                parts.append(self._skills.load_skill_body(skill.name))
        self._skills_cache = (fingerprint, "\n\n".join(parts))

    system_parts.append(self._skills_cache[1])

full_system = "\n\n".join(system_parts)
```

**Step 4: Run tests to verify they pass**
```bash
uv run pytest tests/core/test_memory.py -v
```

**Step 5: Lint and type-check**
```bash
uv run ruff check squidbot/core/memory.py
uv run mypy squidbot/core/memory.py
```

**Step 6: Commit**
```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "perf(memory): cache skills XML assembly; use list-join for system prompt"
```

---

## Task 6: In-memory ring-buffer cache in JsonlMemory

**Files:**
- Modify: `squidbot/adapters/persistence/jsonl.py`
- Test: `tests/adapters/persistence/test_jsonl.py`

**Step 1: Write the failing test**

```python
async def test_load_history_uses_cache_after_first_load(tmp_path: Path) -> None:
    """After the first load_history call no disk read occurs for subsequent calls."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.core.models import Message

    mem = JsonlMemory(base_dir=tmp_path)
    msg = Message(role="user", content="cached?", channel="cli", sender_id="u")

    # Write one message to disk
    await mem.append_message(msg)

    # First load: reads from disk, populates cache
    result1 = await mem.load_history(last_n=10)
    assert len(result1) == 1

    # Delete the history file — second load must come from cache
    history_path = tmp_path / "history.jsonl"
    history_path.unlink()
    assert not history_path.exists()

    result2 = await mem.load_history(last_n=10)
    assert len(result2) == 1
    assert result2[0].content == "cached?"
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/adapters/persistence/test_jsonl.py::test_load_history_uses_cache_after_first_load -v
```

**Step 3: Implement**

Add cache fields to `JsonlMemory.__init__`:
```python
self._history_cache: list[Message] = []
self._history_cache_size: int = 0  # largest last_n ever requested
```

Add cache check at the top of `load_history`:
```python
async def load_history(self, last_n: int | None = None) -> list[Message]:
    if last_n is not None and last_n <= 0:
        return []

    # Cache hit: cache holds enough entries for this request
    if (
        last_n is not None
        and last_n <= self._history_cache_size
        and len(self._history_cache) >= last_n
    ):
        return list(self._history_cache[-last_n:])

    # Cache miss: read from disk (existing _read logic unchanged)
    path = _history_file(self._base)
    # ... existing _read closure and asyncio.to_thread call ...

    # Populate cache after disk read
    if last_n is not None:
        self._history_cache_size = max(self._history_cache_size, last_n)
        self._history_cache = list(messages[-self._history_cache_size:])

    return messages
```

Add cache fields to `JsonlMemory.__init__`. Use `collections.deque(maxlen=N)` for O(1)
appends and automatic trimming instead of a list slice on every write:
```python
import collections

self._history_cache: collections.deque[Message] = collections.deque()
self._history_cache_size: int = 0  # largest last_n ever requested
```

Update the cache-hit check in `load_history` accordingly:
```python
if (
    last_n is not None
    and last_n <= self._history_cache_size
    and len(self._history_cache) >= last_n
):
    return list(self._history_cache)[-last_n:]
```

After the disk read, populate the deque:
```python
if last_n is not None:
    self._history_cache_size = max(self._history_cache_size, last_n)
    self._history_cache = collections.deque(
        messages[-self._history_cache_size:], maxlen=self._history_cache_size
    )
```

Update `append_message` to maintain cache after a successful write:
```python
async def append_message(self, message: Message) -> None:
    path = _history_file(self._base)

    def _write() -> None:
        with path.open("a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(_serialize_message(message) + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    await asyncio.to_thread(_write)
    # Update cache AFTER successful write — never ahead of disk.
    # deque with maxlen trims automatically in O(1).
    if self._history_cache_size > 0:
        if self._history_cache.maxlen != self._history_cache_size:
            self._history_cache = collections.deque(
                self._history_cache, maxlen=self._history_cache_size
            )
        self._history_cache.append(message)
```

**Step 4: Run tests to verify they pass**
```bash
uv run pytest tests/adapters/persistence/test_jsonl.py -v
```

**Step 5: Lint, type-check, full suite**
```bash
uv run ruff check squidbot/adapters/persistence/jsonl.py
uv run mypy squidbot/adapters/persistence/
uv run pytest
```

**Step 6: Commit**
```bash
git add squidbot/adapters/persistence/jsonl.py tests/adapters/persistence/test_jsonl.py
git commit -m "perf(persistence): add in-memory ring-buffer cache for recent history"
```

---

## Task 7: Batch write in JsonlMemory + opt-in in MemoryManager

**Files:**
- Modify: `squidbot/adapters/persistence/jsonl.py`
- Modify: `squidbot/core/memory.py`
- Test: `tests/adapters/persistence/test_jsonl.py`

**Step 1: Write the failing test**

```python
async def test_persist_exchange_opens_file_once(tmp_path: Path) -> None:
    """persist_exchange must open history.jsonl only once."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.core.memory import MemoryManager

    mem = JsonlMemory(base_dir=tmp_path)
    manager = MemoryManager(storage=mem)  # type: ignore[arg-type]

    open_count = 0
    real_open = open

    def counting_open(path: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal open_count
        if "history.jsonl" in str(path):
            open_count += 1
        return real_open(path, *args, **kwargs)  # type: ignore[call-overload]

    with patch("builtins.open", side_effect=counting_open):
        await manager.persist_exchange(
            channel="cli", sender_id="user",
            user_message="hello", assistant_reply="world",
        )

    assert open_count == 1, f"history.jsonl was opened {open_count} times"
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/adapters/persistence/test_jsonl.py::test_persist_exchange_opens_file_once -v
```

**Step 3: Implement `append_messages` in `jsonl.py`**

Add new method after `append_message` (not part of MemoryPort protocol):
```python
async def append_messages(self, messages: list[Message]) -> None:
    """Append multiple messages to history in a single file open and lock.

    Args:
        messages: Messages to append in order.
    """
    if not messages:
        return
    path = _history_file(self._base)
    lines = "\n".join(_serialize_message(m) for m in messages) + "\n"

    def _write() -> None:
        with path.open("a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(lines)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    await asyncio.to_thread(_write)
    # Update cache for all messages after successful write
    for message in messages:
        self._history_cache.append(message)
    if self._history_cache_size > 0:
        self._history_cache = self._history_cache[-self._history_cache_size:]
```

**Step 4: Implement opt-in in `memory.py`**

Update `persist_exchange`:
```python
async def persist_exchange(
    self,
    channel: str,
    sender_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    user_msg = Message(
        role="user", content=user_message, channel=channel, sender_id=sender_id
    )
    assistant_msg = Message(
        role="assistant", content=assistant_reply,
        channel=channel, sender_id="assistant",
    )
    if hasattr(self._storage, "append_messages"):
        await self._storage.append_messages([user_msg, assistant_msg])  # type: ignore[union-attr]
    else:
        await self._storage.append_message(user_msg)
        await self._storage.append_message(assistant_msg)
```

**Step 5: Run tests to verify they pass**
```bash
uv run pytest tests/adapters/persistence/test_jsonl.py tests/core/test_memory.py -v
```

**Step 6: Lint, type-check, full suite**
```bash
uv run ruff check squidbot/ && uv run mypy squidbot/ && uv run pytest
```

**Step 7: Commit**
```bash
git add squidbot/adapters/persistence/jsonl.py squidbot/core/memory.py tests/adapters/persistence/test_jsonl.py
git commit -m "perf(persistence): add append_messages batch write; use in persist_exchange"
```

---

## Task 8: RichCliChannel — cache Console() instance

**Files:**
- Modify: `squidbot/adapters/channels/cli.py`
- Test: `tests/adapters/channels/test_rich_cli.py`

**Step 1: Write the failing test**

```python
async def test_console_instantiated_once() -> None:
    """Console() must be created only once, not on every send() call."""
    from unittest.mock import MagicMock, patch
    from squidbot.adapters.channels.cli import RichCliChannel
    from squidbot.core.models import OutboundMessage, Session

    console_instances: list[MagicMock] = []

    def tracking_console(*args: object, **kwargs: object) -> MagicMock:
        instance = MagicMock()
        console_instances.append(instance)
        return instance

    with patch("squidbot.adapters.channels.cli.Console", side_effect=tracking_console):
        channel = RichCliChannel()
        session = Session(channel="cli", sender_id="local")
        msg = OutboundMessage(session=session, text="hello")
        await channel.send(msg)
        await channel.send(msg)

    assert len(console_instances) == 1, (
        f"Console() was instantiated {len(console_instances)} times"
    )
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/adapters/channels/test_rich_cli.py::test_console_instantiated_once -v
```

**Step 3: Implement**

In `RichCliChannel.__init__`:
```python
def __init__(self) -> None:
    """Initialize Rich CLI state."""
    self._session: PromptSession[str] | None = None
    self._console = Console()
```

Update `send` to use `self._console`:
```python
async def send(self, message: OutboundMessage) -> None:
    """Print the response as Markdown via Rich Console."""
    self._console.print(Rule(style="dim"))
    self._console.print("[bold cyan]squidbot ›[/bold cyan]")
    self._console.print(Markdown(message.text))
```

**Step 4: Run tests to verify they pass**
```bash
uv run pytest tests/adapters/channels/test_rich_cli.py -v
```

**Step 5: Lint, type-check, full suite**
```bash
uv run ruff check squidbot/adapters/channels/cli.py && uv run mypy squidbot/adapters/channels/cli.py && uv run pytest
```

**Step 6: Commit**
```bash
git add squidbot/adapters/channels/cli.py tests/adapters/channels/test_rich_cli.py
git commit -m "perf(channels): cache Rich Console() instance in RichCliChannel"
```

---

## Task 9: EmailChannel — cache SSL context

**Files:**
- Modify: `squidbot/adapters/channels/email.py`
- Test: `tests/adapters/channels/test_email.py`

**Step 1: Write the failing test**

```python
async def test_ssl_context_created_once() -> None:
    """ssl.create_default_context() must be called once, not on every send()."""
    import ssl
    from unittest.mock import AsyncMock, MagicMock, patch

    ctx_instances: list[MagicMock] = []

    def tracking_ctx() -> MagicMock:
        ctx = MagicMock(spec=ssl.SSLContext)
        ctx_instances.append(ctx)
        return ctx

    # Patch both ssl.create_default_context and aiosmtplib.SMTP to avoid real network
    with (
        patch("squidbot.adapters.channels.email.ssl.create_default_context",
              side_effect=tracking_ctx),
        patch("squidbot.adapters.channels.email.aiosmtplib.SMTP") as mock_smtp_cls,
    ):
        # Provide a usable async context manager for SMTP
        smtp_instance = AsyncMock()
        smtp_instance.__aenter__ = AsyncMock(return_value=smtp_instance)
        smtp_instance.__aexit__ = AsyncMock(return_value=False)
        mock_smtp_cls.return_value = smtp_instance

        # Read email.py to find the exact config class and required fields,
        # then build a minimal config with tls=True, tls_verify=True.
        # Replace EmailConfig(...) below with the actual constructor.
        from squidbot.adapters.channels.email import EmailChannel
        # channel = EmailChannel(config=EmailConfig(tls=True, tls_verify=True, ...))
        # await channel._send_reply(to_addr="a@b.com", subject="s", body="b",
        #                           in_reply_to=None, references=None, attachments=[])
        # await channel._send_reply(to_addr="c@d.com", subject="s2", body="b2",
        #                           in_reply_to=None, references=None, attachments=[])

    assert len(ctx_instances) == 1, (
        f"ssl.create_default_context() called {len(ctx_instances)} times"
    )
```

> **Note:** Fill in the `EmailConfig` constructor and `_send_reply` call signature by
> reading `squidbot/adapters/channels/email.py` before writing the test. The structure
> above is complete; only the config construction and method name need confirming.

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/adapters/channels/test_email.py -k "ssl" -v
```

**Step 3: Implement**

Move the SSL context construction into `__init__`. Store as `self._ssl_ctx`:
```python
import ssl

# In __init__:
self._ssl_ctx: ssl.SSLContext | None = None
if config.tls:
    self._ssl_ctx = ssl.create_default_context()
    if not config.tls_verify:
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE
```

In `_send_reply` and `_connect_imap`, replace the local `ssl_ctx` construction
with `ssl_ctx = self._ssl_ctx`.

**Step 4: Run tests to verify they pass**
```bash
uv run pytest tests/adapters/channels/test_email.py -v
```

**Step 5: Lint, type-check, full suite**
```bash
uv run ruff check squidbot/adapters/channels/email.py && uv run mypy squidbot/adapters/channels/ && uv run pytest
```

**Step 6: Commit**
```bash
git add squidbot/adapters/channels/email.py tests/adapters/channels/test_email.py
git commit -m "perf(email): cache SSLContext in __init__ instead of recreating per send"
```

---

## Task 10: AgentLoop — parallel tool execution

**Files:**
- Modify: `squidbot/core/agent.py`
- Test: `tests/core/test_agent.py`

**Step 1: Write the failing test**

Read `tests/core/test_agent.py` first to copy the existing `ScriptedLLM` and
`CollectingChannel` test doubles. Then write:

```python
async def test_tool_calls_executed_in_parallel() -> None:
    """Multiple tool calls from one LLM turn must execute concurrently."""
    import asyncio
    import time
    from typing import Any

    call_start_times: list[float] = []

    class SlowTool:
        name = "slow_tool"
        description = "A slow tool"
        parameters: dict[str, Any] = {"type": "object", "properties": {}}

        async def execute(self, **kwargs: Any) -> ToolResult:
            call_start_times.append(time.monotonic())
            await asyncio.sleep(0.05)
            return ToolResult(tool_call_id="", content="done")

    # ScriptedLLM: first turn returns two tool calls, second turn returns text.
    # Copy ScriptedLLM and CollectingChannel from the existing test_agent.py doubles.
    two_tool_calls = [
        ToolCall(id="tc1", name="slow_tool", arguments={}),
        ToolCall(id="tc2", name="slow_tool", arguments={}),
    ]
    llm = ScriptedLLM(responses=[two_tool_calls, "done"])

    registry = ToolRegistry()
    registry.register(SlowTool())

    from squidbot.core.memory import MemoryManager
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as tmp:
        storage = JsonlMemory(base_dir=pathlib.Path(tmp))
        memory = MemoryManager(storage=storage)  # type: ignore[arg-type]
        loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt="sys")
        channel = CollectingChannel()
        session = Session(channel="cli", sender_id="local")

        start = time.monotonic()
        await loop.run(session, "run two tools", channel)
        elapsed = time.monotonic() - start

    # Sequential: >= 0.10 s; parallel: ~0.05 s
    assert elapsed < 0.09, f"Tools ran sequentially (elapsed={elapsed:.3f}s)"
    assert len(call_start_times) == 2
    assert abs(call_start_times[1] - call_start_times[0]) < 0.025
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/core/test_agent.py::test_tool_calls_executed_in_parallel -v
```

**Step 3: Implement**

Replace the `for` loop in `_append_tool_results` with `asyncio.gather`. Use
`return_exceptions=True` so that a failing tool does not cancel sibling tasks via
`CancelledError` — threads started by `asyncio.to_thread` cannot be interrupted
mid-execution, so cancellation only corrupts state without stopping the thread.
Exceptions are converted to `ToolResult(is_error=True)` to match the error-as-value
convention:

```python
async def _append_tool_results(
    self,
    messages: list[Message],
    tool_calls: list[ToolCall],
    extra_tools: dict[str, ToolPort],
) -> None:
    async def _execute_one(tool_call: ToolCall) -> Message:
        extra_tool = extra_tools.get(tool_call.name)
        if extra_tool is not None:
            raw = await extra_tool.execute(**tool_call.arguments)
            result = ToolResult(
                tool_call_id=tool_call.id,
                content=raw.content,
                is_error=raw.is_error,
            )
        else:
            result = await self._registry.execute(
                tool_call.name,
                tool_call_id=tool_call.id,
                **tool_call.arguments,
            )
        return Message(
            role="tool",
            content=result.content,
            tool_call_id=tool_call.id,
        )

    results = await asyncio.gather(
        *[_execute_one(tc) for tc in tool_calls],
        return_exceptions=True,
    )
    for tool_call, result_or_exc in zip(tool_calls, results):
        if isinstance(result_or_exc, BaseException):
            messages.append(Message(
                role="tool",
                content=f"Error: {result_or_exc}",
                tool_call_id=tool_call.id,
            ))
        else:
            messages.append(result_or_exc)
```

**Step 4: Run tests to verify they pass**
```bash
uv run pytest tests/core/test_agent.py -v
```

**Step 5: Lint, type-check, full suite**
```bash
uv run ruff check squidbot/core/agent.py && uv run mypy squidbot/core/agent.py && uv run pytest
```

**Step 6: Commit**
```bash
git add squidbot/core/agent.py tests/core/test_agent.py
git commit -m "perf(agent): execute tool calls in parallel with asyncio.gather"
```

---

## Task 11: AgentLoop — remove outbound_metadata dict copy

**Files:**
- Modify: `squidbot/core/agent.py`

**Step 1: Implement**

Replace every occurrence of `dict(outbound_metadata or {})` with `outbound_metadata or {}`
in `agent.py`. There are three occurrences:
- In `_run_llm_stream` (streaming chunk path)
- In `_deliver_final_text` (non-streaming path)
- In `run` (error message path)

`OutboundMessage.metadata` is read-only in all channel implementations; no defensive
copy is needed.

**Step 2: Lint, type-check, full suite**
```bash
uv run ruff check squidbot/core/agent.py && uv run mypy squidbot/core/agent.py && uv run pytest
```

**Step 3: Commit**
```bash
git add squidbot/core/agent.py
git commit -m "perf(agent): remove unnecessary dict copy for outbound_metadata"
```

---

## Task 12: SearchHistoryTool — substring pre-filter

**Files:**
- Modify: `squidbot/adapters/tools/search_history.py`
- Test: `tests/adapters/tools/test_search_history.py`

**Step 1: Write the failing test**

```python
def test_deserialize_not_called_for_non_matching_lines(tmp_path: Path) -> None:
    """deserialize_message_safe must not be called for lines that don't contain the query."""
    from unittest.mock import patch
    from squidbot.adapters.persistence.jsonl import _serialize_message, deserialize_message_safe
    from squidbot.core.models import Message

    history_file = tmp_path / "history.jsonl"
    matching = Message(role="user", content="find me please", channel="c", sender_id="u")
    non_matching = Message(role="user", content="unrelated content", channel="c", sender_id="u")
    history_file.write_text(
        _serialize_message(matching) + "\n" + _serialize_message(non_matching) + "\n",
        encoding="utf-8",
    )

    deserialized_contents: list[str] = []
    real_dsafe = deserialize_message_safe

    def tracking_dsafe(line: str) -> Message | None:
        parsed = real_dsafe(line)
        if parsed is not None:
            deserialized_contents.append(parsed.content)
        return parsed

    with patch(
        "squidbot.adapters.tools.search_history.deserialize_message_safe",
        side_effect=tracking_dsafe,
    ):
        from squidbot.adapters.tools.search_history import _scan_history
        from datetime import datetime, timezone
        results = _scan_history(
            tmp_path, "find me please",
            cutoff=datetime(2000, 1, 1, tzinfo=timezone.utc),
            max_results=10,
        )

    assert len(results) == 1
    # "unrelated content" must not have been deserialized
    assert "unrelated content" not in deserialized_contents, (
        f"Non-matching line was deserialized: {deserialized_contents}"
    )
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/adapters/tools/test_search_history.py::test_deserialize_not_called_for_non_matching_lines -v
```

**Step 3: Implement**

First, change `_serialize_message` in `jsonl.py` to use `ensure_ascii=False`. This
ensures non-ASCII content is stored as raw Unicode rather than `\uXXXX` escapes,
which is a prerequisite for the pre-filter to work correctly for non-ASCII queries:

```python
# In _serialize_message, change the final line from:
return json.dumps(d)
# to:
return json.dumps(d, ensure_ascii=False)
```

Then, in `_scan_history`, add the pre-filter before `deserialize_message_safe`:
```python
for raw_line in history_file:
    line = raw_line.strip()
    if not line:
        continue
    # Skip JSON parsing entirely if the query cannot be in this line.
    # ensure_ascii=False in _serialize_message means content is stored as raw
    # Unicode, so this string check is reliable for all scripts and languages.
    if normalized_query not in line.lower():
        continue
    message = deserialize_message_safe(line)
    # ... rest unchanged
```

**Step 4: Run tests to verify they pass**
```bash
uv run pytest tests/adapters/tools/test_search_history.py -v && uv run pytest
```

**Step 5: Commit**
```bash
git add squidbot/adapters/tools/search_history.py tests/adapters/tools/test_search_history.py
git commit -m "perf(tools): skip JSON deserialization for non-matching lines in search_history"
```

---

## Task 13: ReadFileTool — combine exists + read_text into single to_thread

**Files:**
- Modify: `squidbot/adapters/tools/files.py`
- Test: `tests/adapters/tools/test_files.py`

**Step 1: Write the failing test**

```python
async def test_read_file_uses_single_to_thread(tmp_path: Path) -> None:
    """ReadFileTool must use only one asyncio.to_thread call per file read."""
    import asyncio
    from unittest.mock import patch
    from squidbot.adapters.tools.files import ReadFileTool

    thread_calls: list[object] = []
    real_to_thread = asyncio.to_thread

    async def tracking_to_thread(fn: object, *args: object, **kwargs: object) -> object:
        thread_calls.append(fn)
        return await real_to_thread(fn, *args, **kwargs)  # type: ignore[arg-type]

    test_file = tmp_path / "test.txt"
    test_file.write_text("content", encoding="utf-8")

    tool = ReadFileTool(workspace=tmp_path, restrict_to_workspace=False)
    with patch("squidbot.adapters.tools.files.asyncio.to_thread", side_effect=tracking_to_thread):
        await tool.execute(path=str(test_file))

    assert len(thread_calls) == 1, f"asyncio.to_thread called {len(thread_calls)} times"
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/adapters/tools/test_files.py::test_read_file_uses_single_to_thread -v
```

**Step 3: Implement**

Replace the two-call pattern in `ReadFileTool.execute`:
```python
def _read_file() -> str | None:
    try:
        return resolved.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None

content = await asyncio.to_thread(_read_file)
if content is None:
    return ToolResult(
        tool_call_id="",
        content=f"Error: file not found: {path_raw}",
        is_error=True,
    )
return ToolResult(tool_call_id="", content=content)
```

**Step 4: Run tests to verify they pass**
```bash
uv run pytest tests/adapters/tools/test_files.py -v && uv run pytest
```

**Step 5: Commit**
```bash
git add squidbot/adapters/tools/files.py tests/adapters/tools/test_files.py
git commit -m "perf(tools): combine exists+read_text into single asyncio.to_thread in ReadFileTool"
```

---

## Task 14: gateway.py — connect MCP servers in parallel

**Files:**
- Modify: `squidbot/cli/gateway.py`
- Test: `tests/cli/test_gateway.py` (create if it does not exist)

**Step 1: Write the failing test**

```python
async def test_mcp_servers_connect_in_parallel() -> None:
    """Multiple MCP server connections must be established concurrently."""
    import asyncio
    import time
    from unittest.mock import MagicMock

    connect_starts: list[float] = []

    async def slow_connect() -> list:
        connect_starts.append(time.monotonic())
        await asyncio.sleep(0.05)
        return []

    conn1: MagicMock = MagicMock()
    conn2: MagicMock = MagicMock()
    conn1.connect = slow_connect
    conn2.connect = slow_connect

    from squidbot.cli.gateway import _connect_mcp_servers
    start = time.monotonic()
    await _connect_mcp_servers([conn1, conn2])
    elapsed = time.monotonic() - start

    assert elapsed < 0.09, f"MCP servers connected sequentially (elapsed={elapsed:.3f}s)"
    assert len(connect_starts) == 2
    assert abs(connect_starts[1] - connect_starts[0]) < 0.025
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/cli/test_gateway.py::test_mcp_servers_connect_in_parallel -v
```

**Step 3: Implement**

Add new helper function to `gateway.py`:
```python
async def _connect_mcp_servers(
    connections: list[McpConnectionProtocol],
) -> list[tuple[McpConnectionProtocol, list[ToolPort]]]:
    """Connect all MCP servers concurrently.

    Args:
        connections: Pre-constructed server connection objects.

    Returns:
        List of (connection, tools) pairs in the same order as input.
    """
    async def _connect_one(
        conn: McpConnectionProtocol,
    ) -> tuple[McpConnectionProtocol, list[ToolPort]]:
        tools = await conn.connect()
        return conn, tools

    return list(await asyncio.gather(*[_connect_one(c) for c in connections]))
```

Update `_make_agent_loop` to use it:
```python
if settings.tools.mcp_servers:
    from squidbot.adapters.tools.mcp import McpServerConnection  # noqa: PLC0415

    raw_connections = [
        McpServerConnection(name=name, config=cfg)
        for name, cfg in settings.tools.mcp_servers.items()
    ]
    for conn, tools in await _connect_mcp_servers(raw_connections):
        for tool in tools:
            registry.register(tool)
        mcp_connections.append(conn)
```

**Step 4: Run tests to verify they pass**
```bash
uv run pytest tests/cli/ -v && uv run pytest
```

**Step 5: Lint, type-check**
```bash
uv run ruff check squidbot/cli/gateway.py && uv run mypy squidbot/cli/
```

**Step 6: Commit**
```bash
git add squidbot/cli/gateway.py tests/cli/test_gateway.py
git commit -m "perf(gateway): connect MCP servers in parallel with asyncio.gather"
```

---

## Task 15: gateway.py — MemoryWriteTool singleton + remove owner_aliases copy

**Files:**
- Modify: `squidbot/cli/gateway.py`
- Test: `tests/cli/test_gateway.py`

**Step 1: Write the failing test**

Read `squidbot/cli/gateway.py` to confirm the exact signature of `_channel_loop` and
the imports used within it. Then write:

```python
async def test_memory_write_tool_is_singleton_across_messages(tmp_path: Path) -> None:
    """MemoryWriteTool must be reused across messages, not re-instantiated each time."""
    import asyncio
    from collections.abc import AsyncIterator
    from unittest.mock import AsyncMock, MagicMock, patch

    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.core.models import InboundMessage, OutboundMessage, Session
    from squidbot.cli.gateway import _channel_loop

    instances: list[object] = []
    original_init = None  # will be set inside the patch

    def tracking_init(self: object, **kwargs: object) -> None:
        instances.append(self)

    # Fake channel that yields exactly two messages then stops
    class TwoMessageChannel:
        streaming = False

        async def receive(self) -> AsyncIterator[InboundMessage]:
            session = Session(channel="cli", sender_id="local")
            yield InboundMessage(session=session, text="msg1")
            yield InboundMessage(session=session, text="msg2")

        async def send(self, message: OutboundMessage) -> None: ...
        async def send_typing(self, session_id: str, typing: bool = True) -> None: ...

    # Stub AgentLoop that does nothing
    fake_loop = AsyncMock()

    storage = JsonlMemory(base_dir=tmp_path)

    with patch(
        "squidbot.cli.gateway.MemoryWriteTool.__init__",
        side_effect=tracking_init,
        return_value=None,
    ):
        await _channel_loop(
            channel=TwoMessageChannel(),  # type: ignore[arg-type]
            loop=fake_loop,
            storage=storage,
        )

    assert len(instances) == 1, (
        f"MemoryWriteTool was instantiated {len(instances)} times for 2 messages"
    )
```

**Step 2: Implement**

In both `_channel_loop` and `_dispatch_message_gateway`, move `MemoryWriteTool`
instantiation outside the per-message loop:

```python
# Before the message loop:
memory_write_tool = MemoryWriteTool(storage=storage)

# Inside the loop, replace MemoryWriteTool(storage=storage) with:
extra = [
    memory_write_tool,
    MessageTool(
        # ...
        owner_aliases=owner_aliases or [],  # direct reference, no list()
        # ...
    ),
    *build_context_cron_tools(...),
]
```

Check whether `MessageTool` mutates the `owner_aliases` list internally. If it does,
pass `tuple(owner_aliases or ())` as the default instead of creating a new list each
time.

**Step 3: Lint, type-check, full suite**
```bash
uv run ruff check squidbot/cli/gateway.py && uv run mypy squidbot/cli/ && uv run pytest
```

**Step 4: Commit**
```bash
git add squidbot/cli/gateway.py tests/cli/test_gateway.py
git commit -m "perf(gateway): reuse MemoryWriteTool singleton; remove owner_aliases list copy"
```

---

## Task 16: pool.py — shared AsyncOpenAI client for same api_base

**Files:**
- Modify: `squidbot/adapters/llm/pool.py`
- Modify: `squidbot/adapters/llm/openai.py`
- Test: `tests/adapters/llm/test_pool.py`

**Step 1: Write the failing test**

Read `squidbot/adapters/llm/pool.py` to understand how `PooledLLMAdapter` constructs
its member adapters, then write:

```python
def test_pool_members_share_client_for_same_api_base_and_key() -> None:
    """Two adapters with the same api_base AND api_key must share one AsyncOpenAI client."""
    from unittest.mock import patch, MagicMock

    created_clients: list[MagicMock] = []

    def tracking_openai(**kwargs: object) -> MagicMock:
        client = MagicMock()
        created_clients.append(client)
        return client

    # Read pool.py to determine the correct way to build a PooledLLMAdapter with
    # two entries sharing api_base+api_key. Replace the construction below with
    # the actual API.
    with patch("squidbot.adapters.llm.openai.AsyncOpenAI", side_effect=tracking_openai):
        from squidbot.adapters.llm.pool import PooledLLMAdapter
        # pool = PooledLLMAdapter(members=[
        #     LLMEntry(api_base="https://api.example.com", api_key="key1", model="m1"),
        #     LLMEntry(api_base="https://api.example.com", api_key="key1", model="m2"),
        # ])
        # adapter_a, adapter_b = pool._adapters[0], pool._adapters[1]

    # Same base+key → same client instance
    assert len(created_clients) == 1, (
        f"AsyncOpenAI was constructed {len(created_clients)} times for same api_base+key"
    )
    # adapter_a._client is adapter_b._client  (uncomment once pool internals are known)


def test_pool_members_with_different_keys_get_distinct_clients() -> None:
    """Adapters with the same api_base but different api_keys must get distinct clients."""
    from unittest.mock import patch, MagicMock

    created_clients: list[MagicMock] = []

    def tracking_openai(**kwargs: object) -> MagicMock:
        client = MagicMock()
        created_clients.append(client)
        return client

    with patch("squidbot.adapters.llm.openai.AsyncOpenAI", side_effect=tracking_openai):
        from squidbot.adapters.llm.pool import PooledLLMAdapter
        # pool = PooledLLMAdapter(members=[
        #     LLMEntry(api_base="https://api.example.com", api_key="key1", model="m"),
        #     LLMEntry(api_base="https://api.example.com", api_key="key2", model="m"),
        # ])

    assert len(created_clients) == 2, (
        f"Expected 2 distinct clients for different api_keys, got {len(created_clients)}"
    )
```

**Step 2: Run test to verify it fails**
```bash
uv run pytest tests/adapters/llm/test_pool.py -k "share_client" -v
```

**Step 3: Implement**

Add optional `client` parameter to `OpenAIAdapter.__init__`:
```python
def __init__(
    self,
    api_base: str,
    api_key: str,
    model: str,
    supports_reasoning_content: bool = False,
    *,
    client: AsyncOpenAI | None = None,
) -> None:
    self._client = client or AsyncOpenAI(base_url=api_base, api_key=api_key)
    self._model = model
    self._supports_reasoning_content = supports_reasoning_content
```

In `PooledLLMAdapter` (or wherever adapter instances are constructed), build a
client cache keyed on `(api_base, api_key)`. Both fields are required: two entries
at the same base URL but with different credentials must receive distinct clients:
```python
# Key: (api_base, api_key) — api_key is required to prevent credential cross-contamination
client_cache: dict[tuple[str, str], AsyncOpenAI] = {}
adapters = []
for entry in pool_config.members:
    cache_key = (entry.api_base, entry.api_key)
    if cache_key not in client_cache:
        client_cache[cache_key] = AsyncOpenAI(
            base_url=entry.api_base, api_key=entry.api_key
        )
    adapters.append(OpenAIAdapter(
        api_base=entry.api_base,
        api_key=entry.api_key,
        model=entry.model,
        supports_reasoning_content=entry.supports_reasoning_content,
        client=client_cache[cache_key],
    ))
```

**Step 4: Run tests to verify they pass**
```bash
uv run pytest tests/adapters/llm/ -v && uv run pytest
```

**Step 5: Lint, type-check**
```bash
uv run ruff check squidbot/adapters/llm/ && uv run mypy squidbot/adapters/llm/
```

**Step 6: Commit**
```bash
git add squidbot/adapters/llm/pool.py squidbot/adapters/llm/openai.py tests/adapters/llm/test_pool.py
git commit -m "perf(llm): share AsyncOpenAI client across pool members with same api_base"
```

---

### Final Verification

After all tasks are complete:
```bash
uv run ruff check .
uv run ruff format . --check
uv run mypy squidbot/
uv run pytest
```

All checks must pass before opening the PR:
```bash
gh pr create \
  --title "perf: eliminate 14 performance bottlenecks" \
  --body "$(cat docs/plans/2026-03-02-performance-optimization-design.md)"
```
