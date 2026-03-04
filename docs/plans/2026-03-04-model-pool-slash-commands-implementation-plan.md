# Model/Pool Slash Commands Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add session-scoped slash commands to inspect the last used model and temporarily switch/reset LLM pools for the current logical session.

**Architecture:** Extend slash parsing with `/model` and `/pool` actions, then execute these in `AgentLoop` before LLM calls. Track per-logical-session pool overrides and last-used model IDs in memory. Wire `AgentLoop` to resolve pools dynamically via gateway-provided callbacks while keeping behavior deterministic and owner-policy compatible.

**Tech Stack:** Python 3.14, pytest, ruff, mypy --strict, existing OpenAIAdapter/PooledLLMAdapter and gateway `_resolve_llm` wiring.

---

### Task 1: Add failing parser tests for `/model` and `/pool`

**Files:**
- Modify: `tests/core/test_slash_commands.py`
- Modify: `squidbot/core/slash_commands.py` (later task)

**Step 1: Write the failing test**

```python
def test_slash_model_sets_action() -> None:
    result = handle_slash_command("/model")
    assert result.handled is True
    assert result.action == "model"


def test_slash_pool_sets_action_and_argument() -> None:
    result = handle_slash_command("/pool use smart")
    assert result.handled is True
    assert result.action == "pool"
    assert result.argument == "use smart"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_slash_commands.py -v`
Expected: FAIL because `/model` and `/pool` are currently unknown commands.

**Step 3: Write minimal implementation**

```python
if cmd == "/model":
    return SlashCommandResult(handled=True, action="model")
if cmd == "/pool":
    return SlashCommandResult(handled=True, action="pool", argument=argument)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_slash_commands.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/core/test_slash_commands.py squidbot/core/slash_commands.py
git commit -m "feat(core): parse model and pool slash commands"
```

### Task 2: Expose runtime model identity on LLM adapters

**Files:**
- Modify: `squidbot/adapters/llm/openai.py`
- Modify: `squidbot/adapters/llm/pool.py`
- Modify: `tests/adapters/llm/test_pool.py`
- Modify: `tests/adapters/llm/test_openai_adapter.py`

**Step 1: Write the failing test**

```python
def test_openai_adapter_reports_model_id() -> None:
    adapter = OpenAIAdapter(api_base="https://api.test", api_key="k", model="claude-opus")
    assert adapter.get_last_used_model_id() == "claude-opus"
```

```python
async def test_pool_reports_last_successful_model_id() -> None:
    a1 = _make_failing_adapter(RuntimeError("boom"))
    a2 = _make_streaming_adapter(["ok"])
    a2.get_last_used_model_id = lambda: "claude-haiku"
    pool = PooledLLMAdapter([a1, a2])
    await _collect(pool)
    assert pool.get_last_used_model_id() == "claude-haiku"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/adapters/llm/test_pool.py tests/adapters/llm/test_openai_adapter.py -v`
Expected: FAIL because adapters do not expose model identity yet.

**Step 3: Write minimal implementation**

```python
class OpenAIAdapter:
    def get_last_used_model_id(self) -> str:
        return self._model
```

```python
class PooledLLMAdapter:
    self._last_used_model_id: str | None = None

    def get_last_used_model_id(self) -> str | None:
        return self._last_used_model_id
```

Update fallback path to set `_last_used_model_id` when an adapter succeeds.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/adapters/llm/test_pool.py tests/adapters/llm/test_openai_adapter.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/adapters/llm/openai.py squidbot/adapters/llm/pool.py tests/adapters/llm/test_pool.py tests/adapters/llm/test_openai_adapter.py
git commit -m "feat(llm): expose last-used model identity for runtime introspection"
```

### Task 3: Add failing AgentLoop tests for session-scoped pool/model state

**Files:**
- Modify: `tests/core/test_agent.py`
- Modify: `squidbot/core/agent.py` (later task)

**Step 1: Write the failing test**

```python
async def test_slash_pool_use_switches_llm_for_logical_session(...):
    await loop.run(session, "/pool use smart", channel)
    await loop.run(session, "hello", channel)
    assert resolve_calls[-1] == "smart"
```

```python
async def test_slash_model_reports_last_used_model(...):
    await loop.run(session, "hello", channel)
    await loop.run(session, "/model", channel)
    assert "last_used_model" in channel.sent[-1].text
```

```python
async def test_pool_override_resets_after_new_logical_session(...):
    await loop.run(session, "/pool use smart", channel)
    await loop.run(session, "/new", channel)
    await loop.run(session, "hello", channel)
    assert resolve_calls[-1] == "default"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_agent.py -k "slash and (pool or model)" -v`
Expected: FAIL because AgentLoop does not yet support pool/model slash behavior.

**Step 3: Write minimal implementation**

Add optional constructor args and state:

```python
def __init__(..., default_pool_name: str | None = None, resolve_llm: Callable[[str], LLMPort] | None = None, list_pool_names: Callable[[], list[str]] | None = None):
    self._default_pool_name = default_pool_name
    self._resolve_llm = resolve_llm
    self._list_pool_names = list_pool_names
    self._session_pool_overrides: dict[str, str] = {}
    self._session_last_model: dict[str, str] = {}
```

Handle slash actions:

```python
if slash_result.action == "pool":
    # show/list/use/reset
if slash_result.action == "model":
    # render last used model for logical session
```

Use resolved pool for non-slash turns and capture model ID after successful LLM turn.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_agent.py -k "slash and (pool or model)" -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/core/agent.py tests/core/test_agent.py
git commit -m "feat(core): add session-scoped pool switching and model status slash commands"
```

### Task 4: Wire callbacks from gateway into AgentLoop

**Files:**
- Modify: `squidbot/cli/gateway.py`
- Modify: `tests/adapters/test_llm_wiring.py`

**Step 1: Write the failing test**

```python
async def test_make_agent_loop_wires_pool_resolution_callbacks(tmp_path: Path) -> None:
    loop, _, _ = await _make_agent_loop(settings, storage_dir=tmp_path)
    assert loop._default_pool_name == settings.llm.default_pool
    assert callable(loop._resolve_llm)
    assert callable(loop._list_pool_names)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/adapters/test_llm_wiring.py -v`
Expected: FAIL because callbacks are not passed to AgentLoop yet.

**Step 3: Write minimal implementation**

```python
agent_loop = AgentLoop(
    llm=llm,
    memory=memory,
    registry=registry,
    system_prompt=system_prompt,
    default_pool_name=settings.llm.default_pool,
    resolve_llm=functools.partial(_resolve_llm, settings),
    list_pool_names=lambda: sorted(settings.llm.pools.keys()),
)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/adapters/test_llm_wiring.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/cli/gateway.py tests/adapters/test_llm_wiring.py
git commit -m "feat(cli): wire model pool resolution into agent loop"
```

### Task 5: Update docs and run full quality gates

**Files:**
- Modify: `README.md`
- Verify: `docs/plans/2026-03-04-model-pool-slash-commands-design.md`
- Verify: `docs/plans/2026-03-04-model-pool-slash-commands-implementation-plan.md`

**Step 1: Update slash command documentation**

```markdown
- `/model` — show last used model for current logical session
- `/pool` — show active pool and source (default/override)
- `/pool list` — list available pools
- `/pool use <name>` — temporary pool override for current logical session
- `/pool reset` — revert to default pool for current logical session
```

**Step 2: Run full repository checks**

Run:
- `uv run ruff check .`
- `uv run ruff format . --check`
- `uv run mypy squidbot/`
- `uv run pytest`

Expected: all PASS.

**Step 3: Commit docs and final changes**

```bash
git add README.md docs/plans/2026-03-04-model-pool-slash-commands-design.md docs/plans/2026-03-04-model-pool-slash-commands-implementation-plan.md
git commit -m "docs: add model and pool slash command docs"
```
