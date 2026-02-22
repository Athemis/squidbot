# Bootstrap Files Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single `system_prompt_file` config field with automatic multi-file bootstrap loading (`SOUL.md → USER.md → AGENTS.md → ENVIRONMENT.md`), with per-profile control for sub-agents.

**Architecture:** `_load_bootstrap_prompt(workspace, files)` in `cli/main.py` assembles the system prompt from an ordered list of workspace files, skipping missing ones. Sub-agents get a filtered default allowlist (`AGENTS.md` + `ENVIRONMENT.md`). Profiles can override via `bootstrap_files` and/or `system_prompt_file`.

**Tech Stack:** Python 3.14, Pydantic v2, existing `squidbot/config/schema.py` + `squidbot/cli/main.py` + `squidbot/adapters/tools/spawn.py`

---

## Overview of Changes

| Component | Change |
|---|---|
| `config/schema.py` | Remove `AgentConfig.system_prompt_file`; add `SpawnProfile.bootstrap_files` + `SpawnProfile.system_prompt_file` |
| `cli/main.py` | Replace single-file load with `_load_bootstrap_prompt()`; update `SubAgentFactory` wiring |
| `adapters/tools/spawn.py` | `SubAgentFactory` receives `workspace` + `default_bootstrap_files`; `build()` assembles prompt from profile settings |
| `tests/core/test_config.py` | New tests for `SpawnProfile` bootstrap fields |
| `tests/adapters/test_bootstrap_wiring.py` | New tests for `_load_bootstrap_prompt()` and sub-agent prompt assembly |
| `tests/adapters/tools/test_spawn.py` | Update for new `SubAgentFactory` interface |

### Bootstrap file constants (in `cli/main.py`)

```python
BOOTSTRAP_FILES_MAIN = ["SOUL.md", "USER.md", "AGENTS.md", "ENVIRONMENT.md"]
BOOTSTRAP_FILES_SUBAGENT = ["AGENTS.md", "ENVIRONMENT.md"]
```

### `_load_bootstrap_prompt(workspace, filenames)` helper

```python
def _load_bootstrap_prompt(workspace: Path, filenames: list[str]) -> str:
    parts = []
    for name in filenames:
        path = workspace / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts) if parts else "You are a helpful personal AI assistant."
```

### `SpawnProfile` new fields

```python
class SpawnProfile(BaseModel):
    system_prompt: str = ""           # inline override (existing, kept for compat)
    system_prompt_file: str = ""      # filename relative to workspace
    bootstrap_files: list[str] = Field(default_factory=list)  # [] = use default allowlist
    tools: list[str] = Field(default_factory=list)
    pool: str = ""
```

### Sub-agent prompt assembly logic (in `SubAgentFactory.build()`)

```python
# 1. Bootstrap files: profile.bootstrap_files if set, else default allowlist
files = profile.bootstrap_files if (profile and profile.bootstrap_files) else default_bootstrap_files
prompt_parts = [_load_bootstrap_prompt(self._workspace, files)] if files else []

# 2. system_prompt_file: load and append if set
if profile and profile.system_prompt_file:
    path = self._workspace / profile.system_prompt_file
    if path.exists():
        prompt_parts.append(path.read_text(encoding="utf-8"))

# 3. inline system_prompt: append if set
if profile and profile.system_prompt:
    prompt_parts.append(profile.system_prompt)

child_prompt = "\n\n---\n\n".join(prompt_parts) or "You are a helpful personal AI assistant."
```

---

## Task 1: Update `SpawnProfile` config schema

**Files:**
- Modify: `squidbot/config/schema.py:100-105`
- Test: `tests/core/test_config.py`

**Step 1: Write failing tests**

```python
def test_spawn_profile_bootstrap_files_default():
    profile = SpawnProfile()
    assert profile.bootstrap_files == []
    assert profile.system_prompt_file == ""

def test_spawn_profile_bootstrap_files_set():
    profile = SpawnProfile(bootstrap_files=["SOUL.md", "AGENTS.md"])
    assert profile.bootstrap_files == ["SOUL.md", "AGENTS.md"]

def test_spawn_profile_system_prompt_file():
    profile = SpawnProfile(system_prompt_file="RESEARCHER.md")
    assert profile.system_prompt_file == "RESEARCHER.md"

def test_agent_config_no_longer_has_system_prompt_file():
    cfg = AgentConfig()
    assert not hasattr(cfg, "system_prompt_file")
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/core/test_config.py -k "bootstrap_files or system_prompt_file or no_longer_has" -v
```
Expected: FAIL — fields don't exist yet.

**Step 3: Update `SpawnProfile` and remove `AgentConfig.system_prompt_file`**

In `squidbot/config/schema.py`:

```python
class SpawnProfile(BaseModel):
    """Configuration for a named sub-agent profile."""

    system_prompt: str = ""
    system_prompt_file: str = ""  # filename relative to workspace
    bootstrap_files: list[str] = Field(default_factory=list)  # [] = default allowlist
    tools: list[str] = Field(default_factory=list)
    pool: str = ""  # empty = use llm.default_pool


class AgentConfig(BaseModel):
    """Configuration for agent behavior."""

    workspace: str = str(Path.home() / ".squidbot" / "workspace")
    restrict_to_workspace: bool = True
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
```

**Step 4: Run tests**

```bash
uv run pytest tests/core/test_config.py -v
```
Expected: new tests PASS, no regressions.

**Step 5: Commit**

```bash
git add squidbot/config/schema.py tests/core/test_config.py
git commit -m "feat: add bootstrap_files and system_prompt_file to SpawnProfile, remove system_prompt_file from AgentConfig"
```

---

## Task 2: Add `_load_bootstrap_prompt()` helper and update main agent loading

**Files:**
- Modify: `squidbot/cli/main.py:424-429`
- Test: `tests/adapters/test_bootstrap_wiring.py` (new)

**Step 1: Write failing tests**

```python
# tests/adapters/test_bootstrap_wiring.py
from pathlib import Path
from squidbot.cli.main import _load_bootstrap_prompt, BOOTSTRAP_FILES_MAIN, BOOTSTRAP_FILES_SUBAGENT

def test_load_bootstrap_prompt_all_present(tmp_path):
    (tmp_path / "SOUL.md").write_text("soul content")
    (tmp_path / "AGENTS.md").write_text("agents content")
    result = _load_bootstrap_prompt(tmp_path, ["SOUL.md", "AGENTS.md"])
    assert "soul content" in result
    assert "agents content" in result

def test_load_bootstrap_prompt_missing_files_skipped(tmp_path):
    (tmp_path / "AGENTS.md").write_text("agents content")
    result = _load_bootstrap_prompt(tmp_path, ["SOUL.md", "AGENTS.md"])
    assert "agents content" in result
    assert "soul" not in result.lower()

def test_load_bootstrap_prompt_all_missing_returns_fallback(tmp_path):
    result = _load_bootstrap_prompt(tmp_path, ["SOUL.md", "AGENTS.md"])
    assert result == "You are a helpful personal AI assistant."

def test_load_bootstrap_prompt_separator(tmp_path):
    (tmp_path / "SOUL.md").write_text("soul")
    (tmp_path / "AGENTS.md").write_text("agents")
    result = _load_bootstrap_prompt(tmp_path, ["SOUL.md", "AGENTS.md"])
    assert "---" in result

def test_bootstrap_files_main_order():
    assert BOOTSTRAP_FILES_MAIN == ["SOUL.md", "USER.md", "AGENTS.md", "ENVIRONMENT.md"]

def test_bootstrap_files_subagent():
    assert BOOTSTRAP_FILES_SUBAGENT == ["AGENTS.md", "ENVIRONMENT.md"]
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/adapters/test_bootstrap_wiring.py -v
```
Expected: FAIL — `_load_bootstrap_prompt` and constants don't exist yet.

**Step 3: Add constants and helper to `cli/main.py`**

Add near the top of `_make_agent_loop()` (or as module-level constants + standalone function before `_make_agent_loop`):

```python
BOOTSTRAP_FILES_MAIN: list[str] = ["SOUL.md", "USER.md", "AGENTS.md", "ENVIRONMENT.md"]
BOOTSTRAP_FILES_SUBAGENT: list[str] = ["AGENTS.md", "ENVIRONMENT.md"]


def _load_bootstrap_prompt(workspace: Path, filenames: list[str]) -> str:
    """
    Load and concatenate bootstrap files from the workspace.

    Missing files are silently skipped. Returns a fallback string if no
    files are found.

    Args:
        workspace: Path to the agent workspace directory.
        filenames: Ordered list of filenames to load.

    Returns:
        Concatenated prompt text, separated by horizontal rules.
    """
    parts = []
    for name in filenames:
        file_path = workspace / name
        if file_path.exists():
            parts.append(file_path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts) if parts else "You are a helpful personal AI assistant."
```

Replace the existing system prompt loading block in `_make_agent_loop()`:

```python
# OLD:
system_prompt_path = workspace / settings.agents.system_prompt_file
if system_prompt_path.exists():
    system_prompt = system_prompt_path.read_text(encoding="utf-8")
else:
    system_prompt = "You are a helpful personal AI assistant."

# NEW:
system_prompt = _load_bootstrap_prompt(workspace, BOOTSTRAP_FILES_MAIN)
```

**Step 4: Run tests**

```bash
uv run pytest tests/adapters/test_bootstrap_wiring.py uv run pytest tests/core/ -v
```
Expected: all PASS.

**Step 5: Run full suite + lint**

```bash
uv run ruff check . && uv run mypy squidbot/ && uv run pytest -q
```
Expected: all clean.

**Step 6: Commit**

```bash
git add squidbot/cli/main.py tests/adapters/test_bootstrap_wiring.py
git commit -m "feat: replace system_prompt_file with multi-file bootstrap loading (SOUL/USER/AGENTS/ENVIRONMENT)"
```

---

## Task 3: Update `SubAgentFactory` to support bootstrap-aware prompt assembly

**Files:**
- Modify: `squidbot/adapters/tools/spawn.py:114-188`
- Test: `tests/adapters/tools/test_spawn.py`

**Step 1: Write failing tests**

```python
# Add to tests/adapters/tools/test_spawn.py

def test_subagent_uses_default_bootstrap_files(tmp_path):
    """No profile → loads AGENTS.md + ENVIRONMENT.md from workspace."""
    (tmp_path / "AGENTS.md").write_text("agents instructions")
    (tmp_path / "ENVIRONMENT.md").write_text("env notes")

    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=MagicMock(_tools={}),
        workspace=tmp_path,
        default_bootstrap_files=["AGENTS.md", "ENVIRONMENT.md"],
        profiles={},
        default_pool="default",
        resolve_llm=MagicMock(return_value=MagicMock()),
    )
    loop = factory.build(system_prompt_override=None, tools_filter=None)
    assert "agents instructions" in loop._system_prompt
    assert "env notes" in loop._system_prompt

def test_subagent_profile_bootstrap_files_override(tmp_path):
    """profile.bootstrap_files replaces default allowlist."""
    (tmp_path / "SOUL.md").write_text("soul content")
    (tmp_path / "AGENTS.md").write_text("agents")

    profile = SpawnProfile(bootstrap_files=["SOUL.md"])
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=MagicMock(_tools={}),
        workspace=tmp_path,
        default_bootstrap_files=["AGENTS.md", "ENVIRONMENT.md"],
        profiles={"custom": profile},
        default_pool="default",
        resolve_llm=MagicMock(return_value=MagicMock()),
    )
    loop = factory.build(system_prompt_override=None, tools_filter=None, profile_name="custom")
    assert "soul content" in loop._system_prompt
    assert "agents" not in loop._system_prompt

def test_subagent_profile_system_prompt_file(tmp_path):
    """profile.system_prompt_file is loaded and appended."""
    (tmp_path / "AGENTS.md").write_text("agents")
    (tmp_path / "RESEARCHER.md").write_text("researcher instructions")

    profile = SpawnProfile(system_prompt_file="RESEARCHER.md")
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=MagicMock(_tools={}),
        workspace=tmp_path,
        default_bootstrap_files=["AGENTS.md", "ENVIRONMENT.md"],
        profiles={"researcher": profile},
        default_pool="default",
        resolve_llm=MagicMock(return_value=MagicMock()),
    )
    loop = factory.build(system_prompt_override=None, tools_filter=None, profile_name="researcher")
    assert "agents" in loop._system_prompt
    assert "researcher instructions" in loop._system_prompt

def test_subagent_profile_all_combined(tmp_path):
    """bootstrap_files + system_prompt_file + system_prompt all combined."""
    (tmp_path / "SOUL.md").write_text("soul")
    (tmp_path / "EXTRA.md").write_text("extra file")

    profile = SpawnProfile(
        bootstrap_files=["SOUL.md"],
        system_prompt_file="EXTRA.md",
        system_prompt="inline instructions",
    )
    factory = SubAgentFactory(
        memory=MagicMock(),
        registry=MagicMock(_tools={}),
        workspace=tmp_path,
        default_bootstrap_files=["AGENTS.md", "ENVIRONMENT.md"],
        profiles={"combo": profile},
        default_pool="default",
        resolve_llm=MagicMock(return_value=MagicMock()),
    )
    loop = factory.build(system_prompt_override=None, tools_filter=None, profile_name="combo")
    assert "soul" in loop._system_prompt
    assert "extra file" in loop._system_prompt
    assert "inline instructions" in loop._system_prompt
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -k "bootstrap" -v
```
Expected: FAIL — `SubAgentFactory` doesn't accept `workspace` or `default_bootstrap_files` yet.

**Step 3: Update `SubAgentFactory`**

```python
class SubAgentFactory:
    def __init__(
        self,
        memory: MemoryManager,
        registry: ToolRegistry,
        workspace: Path,
        default_bootstrap_files: list[str],
        system_prompt: str,  # REMOVE this parameter
        profiles: dict[str, SpawnProfile],
        default_pool: str,
        resolve_llm: Callable[[str], LLMPort],
    ) -> None:
        self._memory = memory
        self._registry = registry
        self._workspace = workspace
        self._default_bootstrap_files = default_bootstrap_files
        self._profiles = profiles
        self._default_pool = default_pool
        self._resolve_llm = resolve_llm
```

Remove `system_prompt` parameter — it's replaced by `workspace` + `default_bootstrap_files`.

Update `build()`:

```python
def build(
    self,
    system_prompt_override: str | None,
    tools_filter: list[str] | None,
    profile_name: str | None = None,
) -> AgentLoop:
    profile = self._profiles.get(profile_name) if profile_name else None
    pool = (profile.pool if profile and profile.pool else None) or self._default_pool
    llm = self._resolve_llm(pool)

    # Assemble system prompt from bootstrap files + profile overrides
    # 1. Bootstrap files: profile list if set, else default allowlist
    bootstrap_files = (
        profile.bootstrap_files if (profile and profile.bootstrap_files)
        else self._default_bootstrap_files
    )
    prompt_parts: list[str] = []
    if bootstrap_files:
        base = _load_bootstrap_prompt(self._workspace, bootstrap_files)
        if base:
            prompt_parts.append(base)

    # 2. system_prompt_file from profile
    if profile and profile.system_prompt_file:
        file_path = self._workspace / profile.system_prompt_file
        if file_path.exists():
            prompt_parts.append(file_path.read_text(encoding="utf-8"))

    # 3. inline system_prompt from profile or override
    inline = system_prompt_override or (profile.system_prompt if profile else "")
    if inline:
        prompt_parts.append(inline)

    child_prompt = "\n\n---\n\n".join(prompt_parts) or "You are a helpful personal AI assistant."

    child_registry = ToolRegistry()
    for tool in self._registry._tools.values():
        if tool.name in _SPAWN_TOOL_NAMES:
            continue
        if tools_filter is not None and tool.name not in tools_filter:
            continue
        child_registry.register(tool)

    return AgentLoop(
        llm=llm,
        memory=self._memory,
        registry=child_registry,
        system_prompt=child_prompt,
    )
```

Note: `_load_bootstrap_prompt` must be importable from `cli/main.py` — either move it to a shared module or duplicate it in `spawn.py`. Since `spawn.py` cannot import from `cli/`, pass it as a callable or duplicate the small helper. **Simplest: duplicate the helper in `spawn.py`** (it's 8 lines).

**Step 4: Update `_make_agent_loop()` wiring in `cli/main.py`**

```python
spawn_factory = SubAgentFactory(
    memory=memory,
    registry=registry,
    workspace=workspace,
    default_bootstrap_files=BOOTSTRAP_FILES_SUBAGENT,
    profiles=settings.tools.spawn.profiles,
    default_pool=settings.llm.default_pool,
    resolve_llm=functools.partial(_resolve_llm, settings),
)
```

Remove `system_prompt=system_prompt` from `SubAgentFactory(...)`.

**Step 5: Run tests**

```bash
uv run pytest tests/adapters/tools/test_spawn.py -v
```
Expected: all PASS.

**Step 6: Run full suite + lint**

```bash
uv run ruff check . && uv run mypy squidbot/ && uv run pytest -q
```
Expected: all clean.

**Step 7: Commit**

```bash
git add squidbot/adapters/tools/spawn.py squidbot/cli/main.py tests/adapters/tools/test_spawn.py
git commit -m "feat: bootstrap-aware SubAgentFactory with profile bootstrap_files and system_prompt_file"
```

---

## Task 4: Update onboard wizard

**Files:**
- Modify: `squidbot/cli/main.py` (`_run_onboard()`)

**Step 1: Read current onboard implementation**

```bash
grep -n "onboard\|AGENTS\|system_prompt\|write" squidbot/cli/main.py | grep -A2 "_run_onboard"
```

**Step 2: Update template creation**

In `_run_onboard()`, create all four bootstrap files with sensible templates if they don't already exist:

```python
BOOTSTRAP_TEMPLATES = {
    "SOUL.md": "# Soul\n\nDescribe the bot's personality, values, and communication style here.\n",
    "USER.md": "# User\n\nAdd information about yourself here: name, timezone, preferences, context.\n",
    "AGENTS.md": "# Agent Instructions\n\nAdd operative instructions here: tools, workflows, conventions.\n",
    "ENVIRONMENT.md": "# Environment\n\nAdd your local setup notes here: SSH hosts, device names, aliases.\n",
}

for filename, template in BOOTSTRAP_TEMPLATES.items():
    file_path = workspace / filename
    if not file_path.exists():
        file_path.write_text(template, encoding="utf-8")
```

**Step 3: Run full suite**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy squidbot/
```
Expected: all clean.

**Step 4: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "feat: onboard wizard creates SOUL/USER/AGENTS/ENVIRONMENT.md templates"
```

---

## Task 5: Update design docs and README

**Step 1: Update `docs/plans/2026-02-21-squidbot-design.md`**

- In the "Configuration" section: remove `system_prompt_file` field from the example config
- Add new "Bootstrap Files" section describing the four files, their purpose, loading order, and sub-agent allowlist

**Step 2: Update `docs/plans/2026-02-22-spawn-tool-design.md`**

- Update `SpawnProfile` schema to show `bootstrap_files` and `system_prompt_file`
- Update the "Precedence for system_prompt" note
- Remove mention of `system_prompt` as the only override mechanism

**Step 3: Update `README.md`**

- In the config YAML example: remove `system_prompt_file`, add comment about bootstrap files
- Add brief note about `SOUL.md`, `USER.md`, `AGENTS.md`, `ENVIRONMENT.md` in the workspace layout section

**Step 4: Commit**

```bash
git add docs/plans/2026-02-21-squidbot-design.md docs/plans/2026-02-22-spawn-tool-design.md README.md
git commit -m "docs: update bootstrap files design and README workspace layout"
```

---

## Final Verification

```bash
uv run pytest -q
uv run ruff check .
uv run mypy squidbot/
```

All 3 must be clean before considering the feature complete.
