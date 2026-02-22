# Sub-Agent Spawn Tool — Design

## Overview

The `spawn` tool enables a parent agent to delegate tasks to isolated sub-agents that run
concurrently as asyncio Tasks. The parent continues its own execution, spawning multiple
sub-agents if needed, and later waits for results via `spawn_await`.

Sub-agents are configured via named **profiles** defined in `squidbot.yaml`. Each profile
specifies a system prompt and an optional tool subset. If no profile is given, the sub-agent
inherits the parent's system prompt and full tool registry.

---

## Use Cases

- Long research tasks running in parallel while the parent coordinates
- Isolated code execution in a restricted tool environment
- Specialised agents (researcher, coder, writer) invoked by name

---

## Architecture

```
Parent AgentLoop
    │
    ├─ tool_call: spawn(task="...", profile="researcher")
    │       └─ asyncio.Task started → returns job_id immediately
    │
    ├─ tool_call: spawn(task="...", profile="coder")
    │       └─ asyncio.Task started → returns job_id immediately
    │
    └─ tool_call: spawn_await(job_ids="job1,job2")
            └─ asyncio.gather(job1, job2)
                    ├─ [job1: OK]\n<result text>
                    └─ [job2: ERROR]\n<error message>
```

---

## Two-Tool Design

### `spawn`

Starts a sub-agent as a background asyncio Task. Returns immediately with a `job_id`.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `task` | string | yes | The task description for the sub-agent |
| `profile` | string | no | Named profile from config (enum of configured names) |
| `context` | string | no | Additional context injected into the user message |
| `system_prompt` | string | no | Overrides profile or inherited system prompt |
| `tools` | string | no | Comma-separated tool whitelist; overrides profile tools |

**System prompt assembly (in order, all combined):**
1. `bootstrap_files` from profile (or default sub-agent allowlist: `AGENTS.md` + `ENVIRONMENT.md`)
2. `system_prompt_file` from profile (loaded from workspace, appended)
3. `system_prompt` param (explicit override, appended last)

**Precedence for tools:** explicit `tools` param > profile tools > all tools (parent registry).

**Returns:** `job_id` (short UUID, e.g. `"a3f9c1"`)

**Errors:** `is_error=True` if `task` is missing/empty, or if a named profile does not exist.

---

### `spawn_await`

Waits for one or more jobs and returns all results bundled.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `job_ids` | string | yes | Comma-separated job IDs, or `"*"` for all pending jobs |

**Returns:** One block per job, separated by blank lines:

```
[a3f9c1: OK]
<sub-agent result text>

[b7d2e4: ERROR]
<error message>

[unknown_id: NOT FOUND]
```

`is_error` is always `False` — the parent receives all results regardless of sub-agent failures.
Individual job failures are signalled via `[job_id: ERROR]` markers in the content.

---

## Classes (`adapters/tools/spawn.py`)

### `SpawnProfile`

Pydantic model (defined in `config/schema.py`):

```python
class SpawnProfile(BaseModel):
    system_prompt: str = ""           # inline prompt, appended last
    system_prompt_file: str = ""      # filename relative to workspace, appended second
    bootstrap_files: list[str] = []   # bootstrap file list; empty = default sub-agent allowlist
    tools: list[str] = []             # empty = all tools
    pool: str = ""                    # empty = llm.default_pool
```

### `CollectingChannel`

Internal non-streaming channel used by sub-agents:

- `streaming = False`
- `send()` appends text to an internal list
- `receive()` is an async generator that never yields
- `collected_text` property returns the joined result

### `SubAgentFactory`

Builds fresh `AgentLoop` instances for sub-agents:

```python
class SubAgentFactory:
    def __init__(
        self, memory, registry, workspace, default_bootstrap_files,
        profiles, default_pool, resolve_llm
    )
    def build(self, system_prompt_override, tools_filter, profile_name) -> AgentLoop
```

- `workspace` + `default_bootstrap_files` replace the old `system_prompt` parameter
- `build()` assembles the child prompt from bootstrap files + profile overrides (see above)
- `build()` creates a filtered `ToolRegistry` if `tools_filter` is given (keeps only named tools)
- Always excludes `spawn` and `spawn_await` from sub-agent registries to prevent runaway nesting
- Returns a fresh `AgentLoop` with isolated session context

### `JobStore`

In-memory store for running and completed jobs:

```python
class JobStore:
    def start(self, job_id: str, coro: Coroutine) -> None
    async def await_jobs(self, job_ids: list[str]) -> dict[str, str | BaseException]
    def all_job_ids(self) -> list[str]
```

- Uses `asyncio.gather(..., return_exceptions=True)` internally
- Completed tasks are kept in the store so results can be retrieved multiple times

### `SpawnTool`

Implements `ToolPort`. Requires `factory: SubAgentFactory` and `job_store: JobStore`.

- Builds the tool definition dynamically: `profile` parameter has `enum` set to the list of
  configured profile names (empty list → no enum constraint → any string accepted)
- On `execute()`: validates `task`, resolves profile, calls `factory.build()`, creates a
  `CollectingChannel`, wraps `agent_loop.run()` in an asyncio Task via `job_store.start()`

### `SpawnAwaitTool`

Implements `ToolPort`. Requires only `job_store: JobStore`.

- On `execute()`: resolves `"*"` to all job IDs, calls `job_store.await_jobs()`, formats results

---

## Profile Discoverability

Profiles are surfaced to the LLM in two places:

1. **Tool definition `enum`:** The `profile` parameter of `spawn` includes `"enum": ["researcher",
   "coder", ...]` dynamically built from configured profiles. The LLM sees valid choices directly
   when deciding to call the tool.

2. **System prompt injection:** If any profiles are configured, a short block is appended to the
   system prompt at agent startup:

   ```xml
   <available_spawn_profiles>
     <profile name="researcher">Research specialist. Tools: web_search, shell, read_file.</profile>
     <profile name="coder">Coding specialist. Tools: shell, read_file, write_file, list_files.</profile>
   </available_spawn_profiles>
   ```

   This injection is skipped entirely when no profiles are defined, to avoid wasting tokens.

---

## Config Schema (`config/schema.py`)

```yaml
tools:
  spawn:
    enabled: false
    profiles:
      researcher:
        bootstrap_files:              # overrides default sub-agent allowlist
          - "SOUL.md"
          - "AGENTS.md"
        system_prompt_file: "RESEARCHER.md"   # loaded from workspace, appended
        system_prompt: "Focus on academic sources."  # inline, appended last
        tools:
          - web_search
          - shell
          - read_file
        pool: "smart"
      coder:
        system_prompt: "You are a coding specialist. Write clean, tested code."
        tools:
          - shell
          - read_file
          - write_file
          - list_files
```

New Pydantic model `SpawnSettings` with `enabled: bool` and `profiles: dict[str, SpawnProfile]`.
Nested under `tools.spawn` in the existing `ToolSettings`.

---

## Wiring (`cli/main.py` — `_make_agent_loop()`)

```python
if settings.tools.spawn.enabled:
    from squidbot.adapters.tools.spawn import (
        JobStore, SpawnAwaitTool, SpawnTool, SubAgentFactory
    )
    factory = SubAgentFactory(
        llm=llm,
        memory=memory,
        registry=registry,
        workspace=workspace,
        default_bootstrap_files=["AGENTS.md", "ENVIRONMENT.md"],
        profiles=settings.tools.spawn.profiles,
        default_pool=settings.llm.default_pool,
        resolve_llm=resolve_llm,
    )
    job_store = JobStore()
    registry.register(SpawnTool(factory=factory, job_store=job_store))
    registry.register(SpawnAwaitTool(job_store=job_store))
```

Profile injection into the system prompt also happens here, before `AgentLoop` is constructed.

---

## Default Behaviour (no profile)

When `spawn` is called without a `profile`:
- Sub-agent loads the default bootstrap allowlist: `AGENTS.md` + `ENVIRONMENT.md`
- Sub-agent gets all tools from the parent registry (minus `spawn`/`spawn_await`)
- `context` and `system_prompt` override params still apply

---

## Nesting Prevention

`SubAgentFactory.build()` always removes `spawn` and `spawn_await` from the sub-agent's
`ToolRegistry`, regardless of profile or explicit `tools` param. This prevents recursive spawning
without needing a depth counter.

---

## Error Handling Summary

| Situation | Behaviour |
|---|---|
| `task` missing or empty | `ToolResult(is_error=True)` immediately |
| Unknown profile name | `ToolResult(is_error=True)` immediately |
| Sub-agent LLM error | `[job_id: ERROR]\n<message>` in `spawn_await` result |
| Sub-agent Exception | `[job_id: ERROR]\n<exception str>` in `spawn_await` result |
| Unknown job_id in `spawn_await` | `[job_id: NOT FOUND]` in result |
| `spawn_await` with no jobs matching `"*"` | Single line: `No jobs found.` |

---

## Tests

| Test | What it verifies |
|---|---|
| `SpawnTool.execute()` returns job_id immediately | Non-blocking |
| `SpawnAwaitTool.execute(job_ids="*")` waits for all | Wildcard await |
| `SpawnAwaitTool.execute(job_ids="id1,id2")` waits for subset | Partial await |
| Sub-agent error → `[job_id: ERROR]` in content | Error embedding |
| `spawn` with valid profile → correct system_prompt + tools | Profile resolution |
| `spawn` without profile → inherits parent system_prompt | Default behaviour |
| `spawn` with unknown profile → `is_error=True` | Error handling |
| `spawn` with empty `task` → `is_error=True` | Validation |
| `SubAgentFactory.build()` excludes spawn tools | Nesting prevention |
| `SpawnTool` tool definition has `enum` for known profiles | Discoverability |
| Profile injection in system prompt when profiles exist | Discoverability |
| No profile injection when no profiles configured | Token efficiency |
