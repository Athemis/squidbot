# Slash Command Pack v1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add deterministic cross-channel `/status`, `/history`, and `/remember <text>` slash commands that bypass LLM roundtrips while enforcing owner-only access for all slash commands.

**Architecture:** Extend core slash parsing with action+argument metadata, then dispatch actions in `AgentLoop` before typing/LLM flow. Introduce a channel-aware sender resolver for auth (`matrix_sender_id` provenance on Matrix; sender/session fallback elsewhere), keep behavior channel-agnostic by centralizing handling in core, keep `/history` informational-only (no direct history retrieval), and serialize slash `/remember` read-modify-write with an async lock.

**Tech Stack:** Python 3.14, pytest, ruff, mypy --strict, existing `ToolRegistry`, `MemoryManager`, and tool adapters.

---

## Requirement-to-Test Traceability Matrix

| Requirement | Planned tests |
|---|---|
| Slash commands bypass LLM | existing owner-path tests for `/help` + `/new` in `tests/core/test_agent.py`, plus `tests/core/test_agent.py::test_slash_status_returns_without_llm_call`, `tests/core/test_agent.py::test_slash_history_returns_without_llm_call`, `tests/core/test_agent.py::test_slash_remember_returns_without_llm_call` |
| Owner-only all slash commands | `tests/core/test_agent.py::test_slash_help_denied_for_non_owner`, `tests/core/test_agent.py::test_slash_new_denied_for_non_owner`, `tests/core/test_agent.py::test_slash_status_denied_for_non_owner`, `tests/core/test_agent.py::test_slash_history_denied_for_non_owner`, `tests/core/test_agent.py::test_slash_remember_denied_for_non_owner` |
| `/status` stable response schema | `tests/core/test_agent.py::test_slash_status_response_contract` |
| `/history` informational-only behavior | `tests/core/test_agent.py::test_slash_history_returns_informational_guidance_without_llm_call` |
| Matrix sender provenance for slash auth | `tests/core/test_agent.py::test_slash_matrix_owner_allowed_via_metadata_sender`, `tests/core/test_agent.py::test_slash_matrix_non_owner_denied_via_metadata_sender` |
| Missing attribution => deterministic deny | `tests/core/test_agent.py::test_slash_matrix_missing_sender_metadata_denied` |
| `/remember` no lost updates for concurrent slash calls | `tests/core/test_agent.py::test_slash_remember_concurrent_calls_preserve_both_notes` |
| Cross-channel parity of slash behavior | `tests/adapters/test_channel_loops.py::test_channel_loop_forwards_slash_messages_channel_agnostic` |
| Existing `/help` + `/new` behavior for owner unchanged | existing slash tests in `tests/core/test_agent.py` with owner sender + parser regression tests |

### Task 1: Add failing parser tests (including validation and command metadata)

**Files:**
- Create: `tests/core/test_slash_commands.py`
- Modify: `squidbot/core/slash_commands.py` (later task)

**Step 1: Write RED tests for parser behavior**

```python
from squidbot.core.slash_commands import handle_slash_command


def test_slash_status_sets_action() -> None:
    result = handle_slash_command("/status")
    assert result.handled is True
    assert result.action == "status"


def test_slash_history_is_informational() -> None:
    result = handle_slash_command("/history")
    assert result.handled is True
    assert result.action == "history"
    assert result.is_error is False


def test_slash_remember_requires_argument() -> None:
    result = handle_slash_command("/remember   ")
    assert result.handled is True
    assert result.is_error is True
    assert result.response_text == "Usage: /remember <text>"
```

**Step 2: Run RED tests**

Run: `uv run pytest tests/core/test_slash_commands.py -v`
Expected: FAIL because metadata fields and command branches do not exist yet.

**Step 3: Commit RED tests**

```bash
git add tests/core/test_slash_commands.py
git commit -m "test(core): add slash parser red tests for command pack"
```

### Task 2: Implement slash parser extensions and help text updates

**Files:**
- Modify: `squidbot/core/slash_commands.py`
- Test: `tests/core/test_slash_commands.py`

**Step 1: Extend `SlashCommandResult` contract**

```python
@dataclass(frozen=True)
class SlashCommandResult:
    handled: bool
    response_text: str = ""
    reset_requested: bool = False
    action: str | None = None
    argument: str | None = None
    is_error: bool = False
```

**Step 2: Parse command + argument and add branches**

```python
cmd, arg = _split_slash_input(stripped)

if cmd == "/status":
    return SlashCommandResult(handled=True, action="status")
if cmd == "/history":
    return SlashCommandResult(handled=True, action="history")
if cmd == "/remember":
    if not arg:
        return SlashCommandResult(handled=True, is_error=True, response_text="Usage: /remember <text>")
    return SlashCommandResult(handled=True, action="remember", argument=arg)
```

**Step 3: Update `HELP_TEXT` with all commands**

**Step 4: Run parser tests to GREEN**

Run: `uv run pytest tests/core/test_slash_commands.py -v`
Expected: PASS.

**Step 5: Commit parser changes**

```bash
git add squidbot/core/slash_commands.py tests/core/test_slash_commands.py
git commit -m "feat(core): extend slash parser with command metadata"
```

### Task 3: Add failing core tests for authorization and `/status` contract

**Files:**
- Modify: `tests/core/test_agent.py`
- Modify: `squidbot/core/memory.py` (later task)
- Modify: `squidbot/core/agent.py` (later task)

**Step 1: Write RED tests for owner-only behavior**

```python
async def test_slash_history_denied_for_non_owner(storage):
    memory = MemoryManager(storage=storage, owner_aliases=[OwnerAliasEntry(address="owner", channel="cli")])
    session = Session(channel="cli", sender_id="guest")
    ...
    await loop.run(session, "/history token", channel)
    assert channel.sent[0].text == "Access denied: slash commands are only available to the owner."
```

```python
async def test_slash_help_denied_for_non_owner(storage): ...
async def test_slash_new_denied_for_non_owner(storage): ...
async def test_slash_status_denied_for_non_owner(storage): ...
async def test_slash_remember_denied_for_non_owner(storage): ...
```

**Step 2: Write RED Matrix sender-provenance tests**

```python
async def test_slash_matrix_owner_allowed_via_metadata_sender(storage):
    # session.sender_id is room-like, owner identity comes from metadata sender
    session = Session(channel="matrix", sender_id="!room:example.org")
    metadata = {"matrix_sender_id": "@owner:example.org"}
    ...


async def test_slash_matrix_non_owner_denied_via_metadata_sender(storage): ...


async def test_slash_matrix_missing_sender_metadata_denied(storage): ...
```

**Step 3: Write RED test for exact `/status` schema**

```python
async def test_slash_status_response_contract(storage, memory):
    await loop.run(SESSION, "/status", channel)
    assert channel.sent[0].text.splitlines() == [
        "Current session status:",
        f"- channel: {SESSION.channel}",
        f"- physical_session: {SESSION.id}",
        f"- logical_session: {SESSION.id}",
        "- next_turn_history_backfill: true",
    ]
```

**Step 4: Add RED test for CLI always-allowed policy**

```python
async def test_slash_cli_always_allowed(storage):
    memory = MemoryManager(storage=storage, owner_aliases=[OwnerAliasEntry(address="someone", channel="email")])
    session = Session(channel="cli", sender_id="random-cli-user")
    ...
    await loop.run(session, "/help", channel)
    assert "Available commands" in channel.sent[0].text
```

**Step 5: Run RED tests**

Run: `uv run pytest tests/core/test_agent.py -v`
Expected: FAIL on missing authorization and exact status formatting.

**Step 6: Commit RED tests**

```bash
git add tests/core/test_agent.py
git commit -m "test(core): add slash auth and status contract red tests"
```

### Task 4: Implement owner authorization and `/status` contract

**Files:**
- Modify: `squidbot/core/memory.py`
- Modify: `squidbot/core/agent.py`
- Test: `tests/core/test_agent.py`

**Step 1: Add public owner-check method on `MemoryManager` with CLI allow policy**

```python
def is_owner_sender(self, sender_id: str | None, channel: str) -> bool:
    if channel == "cli":
        return True
    if sender_id is None:
        return False
    return self._is_owner(sender_id, channel)
```

**Step 2: Add channel-aware sender resolver helper in `AgentLoop`**

```python
def _resolve_slash_actor_sender(
    self,
    session: Session,
    user_sender_id: str | None,
    outbound_metadata: dict[str, Any] | None,
) -> str | None:
    if session.channel == "matrix":
        sender = (outbound_metadata or {}).get("matrix_sender_id")
        return sender if isinstance(sender, str) and sender else None
    if user_sender_id:
        return user_sender_id
    return session.sender_id
```

**Step 3: Add slash authorization guard in `AgentLoop` for all slash commands**

```python
actor_sender = self._resolve_slash_actor_sender(session, user_sender_id, outbound_metadata)
if slash_result.handled and not self._memory.is_owner_sender(actor_sender, session.channel):
    await channel.send(
        OutboundMessage(..., text="Access denied: slash commands are only available to the owner.")
    )
    return
```

**Step 4: Implement fixed `/status` formatter**

```python
def _build_status_text(self, session: Session) -> str:
    ...
```

**Step 5: Run focused tests to GREEN**

Run: `uv run pytest tests/core/test_agent.py -k "slash and (status or denied or cli_always or matrix)" -v`
Expected: PASS.

**Step 6: Commit implementation**

```bash
git add squidbot/core/memory.py squidbot/core/agent.py tests/core/test_agent.py
git commit -m "feat(core): enforce slash auth and status response contract"
```

### Task 5: Add failing tests for `/history` informational behavior

**Files:**
- Modify: `tests/core/test_agent.py`
- Modify: `squidbot/core/agent.py` (later task)

**Step 1: Add RED tests for informational `/history`**

```python
async def test_slash_history_returns_informational_guidance_without_llm_call(storage, memory):
    ...
    await loop.run(SESSION, "/history", channel)
    assert "informational" in channel.sent[0].text.lower()
    assert "search_history" in channel.sent[0].text


async def test_slash_history_ignores_extra_arguments(storage, memory):
    ...
    await loop.run(SESSION, "/history project x", channel)
    assert "search_history" in channel.sent[0].text
```

**Step 2: Run RED tests**

Run: `uv run pytest tests/core/test_agent.py -k "slash and history" -v`
Expected: FAIL because `/history` action is not implemented yet.

**Step 3: Commit RED tests**

```bash
git add tests/core/test_agent.py
git commit -m "test(core): add informational slash history red tests"
```

### Task 6: Implement informational slash `/history` dispatch

**Files:**
- Modify: `squidbot/core/agent.py`
- Modify: `tests/core/test_agent.py`

**Step 1: Add deterministic informational text for `/history` in `AgentLoop`**

```python
def _build_history_info_text(self) -> str:
    return (
        "History command is informational only. "
        "To recall past details, ask me to run search_history with your query."
    )
```

**Step 2: Dispatch `/history` action without tool calls**

```python
if slash_result.action == "history":
    await channel.send(OutboundMessage(session=session, text=self._build_history_info_text(), ...))
    return
```

**Step 3: Add assertion that `/history` does not require `search_history` tool registration**

**Step 4: Run focused tests to GREEN**

Run:
- `uv run pytest tests/core/test_agent.py -k "slash and history" -v`

Expected: PASS.

**Step 5: Commit implementation**

```bash
git add squidbot/core/agent.py tests/core/test_agent.py
git commit -m "feat(core): add informational slash history command"
```

### Task 7: Add failing `/remember` concurrency and error-path tests

**Files:**
- Modify: `tests/core/test_agent.py`
- Modify: `squidbot/core/agent.py` (later task)

**Step 1: Add RED concurrency test**

```python
async def test_slash_remember_concurrent_calls_preserve_both_notes(storage, memory):
    await asyncio.gather(
        loop.run(owner_session, "/remember note-one", channel),
        loop.run(owner_session, "/remember note-two", channel),
    )
    saved = await storage.load_global_memory()
    assert "note-one" in saved
    assert "note-two" in saved
```

**Step 2: Add RED failure-path tests for `/remember`**

- missing `memory_write` tool
- tool raises exception
- tool returns `ToolResult(is_error=True)`

**Step 3: Run RED tests**

Run: `uv run pytest tests/core/test_agent.py -k "slash and remember" -v`
Expected: FAIL due to no lock and incomplete error handling.

**Step 4: Commit RED tests**

```bash
git add tests/core/test_agent.py
git commit -m "test(core): add slash remember concurrency red tests"
```

### Task 8: Implement serialized `/remember` workflow

**Files:**
- Modify: `squidbot/core/agent.py`
- Modify: `squidbot/core/memory.py`
- Test: `tests/core/test_agent.py`

**Step 1: Add shared async lock in `AgentLoop`**

```python
self._remember_lock = asyncio.Lock()
```

**Step 2: Add helper to read global memory text through `MemoryManager`**

```python
async def load_global_memory_text(self) -> str:
    return await self._storage.load_global_memory()
```

**Step 3: Serialize `/remember` read-modify-write**

```python
async with self._remember_lock:
    existing = await self._memory.load_global_memory_text()
    merged = _append_memory_note(existing, note)
    result = await memory_tool.execute(content=merged)
```

**Step 4: Narrow and enforce guarantee scope explicitly**

- Guarantee applies to concurrent slash `/remember` calls only.
- Non-slash `memory_write` write ordering remains existing behavior.
- Ensure docs and test names reflect slash-scoped concurrency guarantee.

**Step 5: Normalize slash error handling for exceptions and error results**

**Step 6: Run focused tests to GREEN**

Run: `uv run pytest tests/core/test_agent.py -k "slash and remember" -v`
Expected: PASS.

**Step 7: Commit implementation**

```bash
git add squidbot/core/agent.py squidbot/core/memory.py tests/core/test_agent.py
git commit -m "fix(core): serialize slash remember writes to avoid races"
```

### Task 9: Add channel-loop parity test for slash forwarding

**Files:**
- Modify: `tests/adapters/test_channel_loops.py`

**Step 1: Add parity-focused test**

```python
async def test_channel_loop_forwards_slash_messages_channel_agnostic():
    # run _channel_loop twice with different channel/session labels (matrix/email)
    # assert loop.run receives slash text unchanged in both cases
```

**Step 2: Run targeted parity tests**

Run: `uv run pytest tests/adapters/test_channel_loops.py -v`
Expected: PASS.

**Step 3: Commit parity test**

```bash
git add tests/adapters/test_channel_loops.py
git commit -m "test(adapters): verify slash forwarding parity across channel loops"
```

### Task 10: Update docs and run full verification gates

**Files:**
- Modify: `README.md`
- Verify: `docs/plans/2026-03-03-slash-command-pack-design.md`
- Verify: `docs/plans/2026-03-03-slash-command-pack-implementation-plan.md`

**Step 1: Update README slash command list and owner-only notes**

```markdown
- Slash commands are owner-only (`/help`, `/new`, `/status`, `/history`, `/remember`)
- `/status` — show current logical session status
- `/history` — informational guidance for explicit history recall
- `/remember <text>` — append memory note
```

**Step 2: Run full quality gates**

Run:
- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run mypy squidbot/`
- `uv run pytest`

Additional verification:
- confirm non-slash Matrix mention/allowlist behavior remains unchanged by slash auth layer
  (`uv run pytest tests/adapters/channels/test_matrix.py -k "mention or allowlist" -v`)

Expected: all PASS.

**Step 3: Final docs commit**

```bash
git add README.md docs/plans/2026-03-03-slash-command-pack-design.md docs/plans/2026-03-03-slash-command-pack-implementation-plan.md
git commit -m "docs: harden slash command pack plan with auth and race controls"
```
