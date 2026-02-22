# Mypy Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate all 12 pre-existing mypy errors so that `uv run mypy squidbot/` exits with 0 errors.

**Architecture:** The fixes fall into 4 independent groups touching `ports.py`, `jsonl.py`, `shell.py`/`files.py`/`web_search.py`/`memory_write.py`, and `cli/main.py`. Each group is one task. No new abstractions are introduced — the errors are genuine conformance bugs, not mypy over-reach.

**Tech Stack:** Python 3.14, mypy (strict), ruff, pytest, asyncio

---

## Error Inventory

```
squidbot/core/ports.py:41      [type-arg]     list without type params
squidbot/core/ports.py:156     [type-arg]     list without type params
squidbot/adapters/persistence/jsonl.py:30  [type-arg]  dict without type params
squidbot/adapters/tools/shell.py:61        [arg-type]  asyncio.wait_for wrong type
squidbot/cli/main.py:301       [arg-type]  ShellTool.execute signature mismatch
squidbot/cli/main.py:302       [arg-type]  ReadFileTool.execute signature mismatch
squidbot/cli/main.py:303       [arg-type]  WriteFileTool.execute signature mismatch
squidbot/cli/main.py:309       [arg-type]  WebSearchTool.execute signature mismatch
squidbot/cli/main.py:347       [arg-type]  CliChannel.receive() wrong return type
squidbot/cli/main.py:359       [assignment] RichCliChannel not assignable to CliChannel var
squidbot/cli/main.py:362       [arg-type]  CliChannel.receive() wrong return type (again)
squidbot/cli/main.py:416       [no-untyped-def] on_cron_due missing type annotation
```

---

## Task 1: Fix `[type-arg]` in `ports.py` and `jsonl.py`

**Files:**
- Modify: `squidbot/core/ports.py:41,156`
- Modify: `squidbot/adapters/persistence/jsonl.py:30`

**What:** Three bare generic types — `list` and `dict` — are missing type parameters.

**Step 1: Fix `ports.py` line 41**

In `LLMPort.chat`, the return type annotation uses bare `list`:

```python
# Line 41 — current:
) -> AsyncIterator[str | list]:

# Fix:
) -> AsyncIterator[str | list[Any]]:
```

`Any` is already imported at the top of `ports.py`.

**Step 2: Fix `ports.py` line 156**

In `SkillsPort.list_skills`, the return type uses bare `list`:

```python
# Line 156 — current:
def list_skills(self) -> list:

# Fix (import SkillMetadata from squidbot.core.skills):
def list_skills(self) -> list[SkillMetadata]:
```

Add import at the top of `ports.py`:
```python
from squidbot.core.skills import SkillMetadata
```

**Step 3: Fix `jsonl.py` line 30**

In `_serialize_message`, the local variable `d` uses bare `dict`:

```python
# Line 30 — current:
d: dict = {

# Fix:
d: dict[str, Any] = {
```

Add `Any` to imports at top of `jsonl.py`:
```python
from typing import Any
```

**Step 4: Verify**

```bash
uv run mypy squidbot/core/ports.py squidbot/adapters/persistence/jsonl.py
```
Expected: 0 errors in these files.

**Step 5: Run full tests**

```bash
uv run ruff check . && uv run pytest -q
```
Expected: ruff clean, 120 passed.

**Step 6: Commit**

```bash
git add squidbot/core/ports.py squidbot/adapters/persistence/jsonl.py
git commit -m "fix: add missing type parameters for list and dict generics"
```

---

## Task 2: Fix `[arg-type]` in `shell.py` — `asyncio.wait_for`

**Files:**
- Modify: `squidbot/adapters/tools/shell.py:61`

**What:** `proc.communicate()` returns `Coroutine[Any, Any, tuple[bytes, bytes]]`, but mypy expects `Future[tuple[bytes, dict[str, object]]] | Awaitable[...]`. The mismatch is that the second element of the tuple is `bytes`, not `dict[str, object]`. This is a mypy/asyncio stub quirk — the fix is to cast or to use `asyncio.wait_for` correctly.

Actually: `proc.communicate()` returns `Coroutine[Any, Any, tuple[bytes, bytes]]`. `asyncio.wait_for` accepts `Awaitable[T]` — a `Coroutine` is `Awaitable`, so this *should* work. The real issue is mypy's stub for `wait_for` is overloaded and one overload requires `Future`. The clean fix is to wrap the call:

```python
# Current (line 61):
stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)

# Fix — explicit cast to Awaitable:
stdout, _ = await asyncio.wait_for(
    asyncio.ensure_future(proc.communicate()), timeout=timeout
)
```

Or simpler — use `cast`:
```python
from typing import cast
import asyncio

stdout_bytes, _ = await asyncio.wait_for(
    cast("asyncio.Future[tuple[bytes, bytes]]", proc.communicate()),
    timeout=timeout,
)
stdout = stdout_bytes.decode(errors="replace")
```

The simplest correct fix that avoids the stub mismatch is:

```python
# Replace line 61:
communicate_result = await asyncio.wait_for(proc.communicate(), timeout=timeout)  # type: ignore[arg-type]
stdout = communicate_result[0].decode(errors="replace")
```

Actually, since we want *zero* `type: ignore`, the best fix is to not use `wait_for` at all for `communicate()`, but instead rely on a manual timeout pattern. However the simplest zero-ignore solution is `asyncio.ensure_future`:

```python
stdout, _ = await asyncio.wait_for(
    asyncio.ensure_future(proc.communicate()), timeout=timeout
)
```

`asyncio.ensure_future` wraps the coroutine in a `Task` (which is a `Future`), satisfying the stub.

**Step 1: Apply fix to `shell.py`**

Replace line 61:
```python
# Before:
stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)

# After:
stdout, _ = await asyncio.wait_for(
    asyncio.ensure_future(proc.communicate()), timeout=timeout
)
```

**Step 2: Verify**

```bash
uv run mypy squidbot/adapters/tools/shell.py
```
Expected: 0 errors.

**Step 3: Run tests**

```bash
uv run pytest tests/adapters/tools/ -q
```
Expected: all pass.

**Step 4: Commit**

```bash
git add squidbot/adapters/tools/shell.py
git commit -m "fix: wrap proc.communicate() in ensure_future to satisfy mypy wait_for stub"
```

---

## Task 3: Fix Tool `execute()` Protocol Conformance

**Files:**
- Modify: `squidbot/adapters/tools/shell.py`
- Modify: `squidbot/adapters/tools/files.py`
- Modify: `squidbot/adapters/tools/web_search.py`
- Modify: `squidbot/adapters/tools/memory_write.py`

**What:** `ToolPort.execute(self, **kwargs: Any)` is the protocol signature. All concrete tools have named parameters like `execute(self, command: str, ...)`. mypy correctly rejects this because a caller using `ToolPort` could pass `execute(foo="bar")` and get a `TypeError` at runtime.

The fix: change all tool `execute` methods to accept `**kwargs: Any` and extract parameters internally. This is the correct Python Protocol pattern for dynamic dispatch.

**Step 1: Fix `ShellTool.execute` in `shell.py`**

```python
# Before:
async def execute(self, command: str, timeout: int = 30, **_: object) -> ToolResult:
    """Run the command and return combined stdout/stderr."""
    cwd = str(self._workspace) if self._restrict and self._workspace else None

# After:
async def execute(self, **kwargs: Any) -> ToolResult:
    """Run the command and return combined stdout/stderr."""
    command: str = str(kwargs.get("command", ""))
    timeout: int = int(kwargs.get("timeout", 30))
    cwd = str(self._workspace) if self._restrict and self._workspace else None
```

Add `from typing import Any` import to `shell.py`.

**Step 2: Fix `ReadFileTool.execute` in `files.py`**

```python
# Before:
async def execute(self, path: str, **_: object) -> ToolResult:
    resolved = _resolve_safe(self._workspace, path, self._restrict)

# After:
async def execute(self, **kwargs: Any) -> ToolResult:
    path: str = str(kwargs.get("path", ""))
    resolved = _resolve_safe(self._workspace, path, self._restrict)
```

**Step 3: Fix `WriteFileTool.execute` in `files.py`**

```python
# Before:
async def execute(self, path: str, content: str, **_: object) -> ToolResult:
    resolved = _resolve_safe(self._workspace, path, self._restrict)

# After:
async def execute(self, **kwargs: Any) -> ToolResult:
    path: str = str(kwargs.get("path", ""))
    content: str = str(kwargs.get("content", ""))
    resolved = _resolve_safe(self._workspace, path, self._restrict)
```

**Step 4: Fix `ListFilesTool.execute` in `files.py`**

```python
# Before:
async def execute(self, path: str = ".", **_: object) -> ToolResult:
    resolved = _resolve_safe(self._workspace, path, self._restrict)

# After:
async def execute(self, **kwargs: Any) -> ToolResult:
    path: str = str(kwargs.get("path", "."))
    resolved = _resolve_safe(self._workspace, path, self._restrict)
```

Add `from typing import Any` import to `files.py`.

**Step 5: Fix `WebSearchTool.execute` in `web_search.py`**

```python
# Before:
async def execute(self, query: str, max_results: int = 5, **_: object) -> ToolResult:

# After:
async def execute(self, **kwargs: Any) -> ToolResult:
    query: str = str(kwargs.get("query", ""))
    max_results: int = int(kwargs.get("max_results", 5))
```

`Any` is already imported via `from typing import Any` in `web_search.py`.

**Step 6: Fix `MemoryWriteTool.execute` in `memory_write.py`**

```python
# Before:
async def execute(self, content: str, **_: object) -> ToolResult:
    await self._storage.save_memory_doc(self._session_id, content)

# After:
async def execute(self, **kwargs: Any) -> ToolResult:
    content: str = str(kwargs.get("content", ""))
    await self._storage.save_memory_doc(self._session_id, content)
```

Add `from typing import Any` import to `memory_write.py`.

**Step 7: Verify**

```bash
uv run mypy squidbot/adapters/tools/
```
Expected: 0 errors.

**Step 8: Run tests**

```bash
uv run pytest -q
```
Expected: 120 passed.

**Step 9: Commit**

```bash
git add squidbot/adapters/tools/shell.py squidbot/adapters/tools/files.py \
        squidbot/adapters/tools/web_search.py squidbot/adapters/tools/memory_write.py
git commit -m "fix: make tool execute() methods conform to ToolPort protocol (**kwargs: Any)"
```

---

## Task 4: Fix Channel and `main.py` Errors

**Files:**
- Modify: `squidbot/core/ports.py`
- Modify: `squidbot/cli/main.py`

**What:** Four issues:

1. `ChannelPort.receive()` is declared `async def` returning `AsyncIterator`, but the concrete implementations are `async def` generator functions — they *are* `AsyncIterator` directly. The protocol must declare `receive` as a plain `def` returning `AsyncIterator` (not `async def`, which would make it a coroutine returning an `AsyncIterator`).

2. `main.py:359` — `channel` is typed as `CliChannel` but reassigned to `RichCliChannel`. Fix: widen the type to `CliChannel | RichCliChannel` or use a `ChannelPort`-typed variable.

3. `main.py:347,362` — `agent_loop.run(...)` receives `CliChannel` but expects `ChannelPort`. This is caused by issue 1: once `receive` is fixed in the protocol, conformance should be satisfied.

4. `main.py:416` — `on_cron_due(job)` missing type annotation. Fix: annotate with `CronJob`.

**Step 1: Fix `ChannelPort.receive()` in `ports.py`**

```python
# Before (line 71):
async def receive(self) -> AsyncIterator[InboundMessage]:
    """Yield inbound messages as they arrive."""
    ...

# After:
def receive(self) -> AsyncIterator[InboundMessage]:
    """Yield inbound messages as they arrive."""
    ...
```

`async def receive()` would mean callers must `await channel.receive()` to get the iterator, but the concrete implementations use `async def receive(self)` as async generators — which means calling them returns an `AsyncIterator` directly (no await needed). The protocol must match: `def receive(self) -> AsyncIterator[InboundMessage]`.

**Step 2: Fix variable type in `main.py` around line 359**

```python
# Before:
channel = CliChannel()
...
channel = RichCliChannel()  # error: RichCliChannel not assignable to CliChannel

# After — import ChannelPort and widen the type:
from squidbot.core.ports import ChannelPort   # add to imports

channel: ChannelPort
...
channel = CliChannel()
...
channel = RichCliChannel()
```

Or simply remove the explicit annotation (let mypy infer `CliChannel | RichCliChannel`).

**Step 3: Annotate `on_cron_due` in `main.py`**

```python
# Before (line 416):
async def on_cron_due(job) -> None:

# After:
async def on_cron_due(job: CronJob) -> None:
```

`CronJob` is already imported in `main.py` via `squidbot.core.models`.

**Step 4: Verify**

```bash
uv run mypy squidbot/
```
Expected: 0 errors.

**Step 5: Run full suite**

```bash
uv run ruff check . && uv run pytest -q
```
Expected: ruff clean, 120 passed.

**Step 6: Commit**

```bash
git add squidbot/core/ports.py squidbot/cli/main.py
git commit -m "fix: correct ChannelPort.receive() signature and annotate on_cron_due"
```

---

## Final Verification

```bash
uv run mypy squidbot/
# Expected: Found no errors (0 errors)

uv run ruff check .
# Expected: All checks passed!

uv run pytest -q
# Expected: 120 passed
```
