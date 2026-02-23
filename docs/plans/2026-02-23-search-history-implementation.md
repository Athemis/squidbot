# Search History Tool Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `search_history` tool that lets the agent search across all JSONL session files for past conversations — enabling episodic memory without embeddings.

**Architecture:** New `ToolPort` adapter at `squidbot/adapters/tools/search_history.py`. Reads JSONL files directly from `base_dir/sessions/`. Only includes `user` and `assistant` roles in output (no tool calls). Returns matches with surrounding context (±1 message). Supports filtering by time period (last N days).

**Tech Stack:** Python 3.14, existing `JsonlMemory` deserialization helpers, `ToolPort` protocol.

---

## Task 1: Implement `SearchHistoryTool`

**Files:**
- Create: `squidbot/adapters/tools/search_history.py`
- Test: `tests/adapters/tools/test_search_history.py`

**Step 1: Write the failing tests**

Create `tests/adapters/tools/test_search_history.py`:

```python
"""
Tests for the search_history tool.
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path

from squidbot.adapters.tools.search_history import SearchHistoryTool
from squidbot.core.models import Message
from squidbot.adapters.persistence.jsonl import JsonlMemory


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def memory(sessions_dir: Path) -> JsonlMemory:
    return JsonlMemory(base_dir=sessions_dir)


@pytest.fixture
def tool(sessions_dir: Path) -> SearchHistoryTool:
    return SearchHistoryTool(base_dir=sessions_dir)


async def test_finds_match_in_single_session(memory: JsonlMemory, tool: SearchHistoryTool):
    await memory.append_message("cli:local", Message(role="user", content="What about Python packaging?"))
    await memory.append_message("cli:local", Message(role="assistant", content="We discussed uv as package manager."))

    result = await tool.execute(query="Python packaging")
    assert result.is_error is False
    assert "Python packaging" in result.content
    assert "uv" in result.content


async def test_case_insensitive_search(memory: JsonlMemory, tool: SearchHistoryTool):
    await memory.append_message("cli:local", Message(role="user", content="DOCKER configuration"))

    result = await tool.execute(query="docker")
    assert result.is_error is False
    assert "DOCKER" in result.content


async def test_searches_across_multiple_sessions(memory: JsonlMemory, tool: SearchHistoryTool):
    await memory.append_message("cli:local", Message(role="user", content="Project Alpha started."))
    await memory.append_message("matrix:user", Message(role="user", content="Project Beta discussion."))

    result = await tool.execute(query="Project")
    assert result.is_error is False
    assert "Alpha" in result.content
    assert "Beta" in result.content


async def test_days_filter_excludes_old_messages(memory: JsonlMemory, tool: SearchHistoryTool):
    # Old message (10 days ago)
    old_msg = Message(role="user", content="Old topic about legacy code.")
    old_msg.timestamp = datetime.now() - timedelta(days=10)
    await memory.append_message("cli:local", old_msg)

    # Recent message
    await memory.append_message("cli:local", Message(role="user", content="Recent topic about new features."))

    result = await tool.execute(query="topic", days=5)
    assert result.is_error is False
    assert "Recent topic" in result.content
    assert "Old topic" not in result.content


async def test_max_results_cap(memory: JsonlMemory, tool: SearchHistoryTool):
    for i in range(20):
        await memory.append_message("cli:local", Message(role="user", content=f"Find me number {i}"))

    result = await tool.execute(query="Find me", max_results=5)
    assert result.is_error is False
    # Should have at most 5 matches
    assert result.content.count("## Match") <= 5


async def test_no_matches_returns_friendly_message(tool: SearchHistoryTool):
    result = await tool.execute(query="nonexistent")
    assert result.is_error is False
    assert "No matches found" in result.content


async def test_tool_calls_excluded_from_search(memory: JsonlMemory, tool: SearchHistoryTool):
    from squidbot.core.models import ToolCall

    await memory.append_message("cli:local", Message(role="user", content="Search for secrets"))
    await memory.append_message("cli:local", Message(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="tc1", name="read_file", arguments={"path": "/etc/secrets"})]
    ))
    await memory.append_message("cli:local", Message(role="tool", content="secret data here", tool_call_id="tc1"))

    result = await tool.execute(query="secrets")
    assert result.is_error is False
    # Should find the user message
    assert "Search for secrets" in result.content
    # Tool call content should not appear in output
    assert "secret data here" not in result.content


async def test_context_includes_surrounding_messages(memory: JsonlMemory, tool: SearchHistoryTool):
    await memory.append_message("cli:local", Message(role="user", content="Before context."))
    await memory.append_message("cli:local", Message(role="user", content="Target keyword here."))
    await memory.append_message("cli:local", Message(role="assistant", content="Response to target."))
    await memory.append_message("cli:local", Message(role="user", content="After context."))

    result = await tool.execute(query="Target keyword")
    assert result.is_error is False
    # Should include surrounding messages
    assert "Before context" in result.content or "After context" in result.content


async def test_query_required(tool: SearchHistoryTool):
    result = await tool.execute()
    assert result.is_error is True
    assert "query is required" in result.content.lower()
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/adapters/tools/test_search_history.py -v
```
Expected: FAIL — module doesn't exist yet

**Step 3: Implement `SearchHistoryTool`**

Create `squidbot/adapters/tools/search_history.py`:

```python
"""
Search history tool — allows the agent to search past conversations.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from squidbot.adapters.persistence.jsonl import _deserialize_message
from squidbot.core.models import Message, ToolDefinition, ToolResult


class SearchHistoryTool:
    """
    Search across all session history files for a text pattern.

    Returns matching user/assistant messages with surrounding context.
    Supports filtering by time period (last N days).
    """

    name = "search_history"
    description = (
        "Search conversation history across all sessions for a text pattern. "
        "Returns matching messages with surrounding context. "
        "Use this to recall past conversations, decisions, or facts the user mentioned."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text to search for (case-insensitive substring match).",
            },
            "days": {
                "type": "integer",
                "description": "Only search messages from the last N days. 0 or omitted = all time.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matches to return (default 10, max 50).",
            },
        },
        "required": ["query"],
    }

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._sessions_dir = base_dir / "sessions"

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        query_raw = kwargs.get("query")
        if not isinstance(query_raw, str) or not query_raw.strip():
            return ToolResult(tool_call_id="", content="Error: query is required", is_error=True)
        query: str = query_raw.strip().lower()

        days: int = 0
        if isinstance(kwargs.get("days"), int):
            days = max(0, kwargs["days"])

        max_results: int = 10
        if isinstance(kwargs.get("max_results"), int):
            max_results = min(50, max(1, kwargs["max_results"]))

        cutoff = datetime.now() - timedelta(days=days) if days > 0 else None

        # Collect all messages from all session files
        all_messages: list[tuple[str, Message]] = []  # (session_id, message)
        if self._sessions_dir.exists():
            for jsonl_file in self._sessions_dir.glob("*.jsonl"):
                session_id = jsonl_file.stem.replace("__", ":")
                for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        try:
                            msg = _deserialize_message(line)
                            all_messages.append((session_id, msg))
                        except Exception:
                            continue

        # Filter by date if specified
        if cutoff:
            all_messages = [(sid, m) for sid, m in all_messages if m.timestamp >= cutoff]

        # Find matches
        matches: list[tuple[str, Message, int]] = []  # (session_id, message, index)
        for idx, (session_id, msg) in enumerate(all_messages):
            if msg.role in ("user", "assistant") and msg.content:
                if query in msg.content.lower():
                    matches.append((session_id, msg, idx))

        if not matches:
            return ToolResult(
                tool_call_id="",
                content=f"No matches found for '{query}'.",
                is_error=False,
            )

        # Limit results
        matches = matches[:max_results]

        # Build output with context
        output_lines: list[str] = []
        for i, (session_id, msg, idx) in enumerate(matches, 1):
            output_lines.append(f"## Match {i} — Session: {session_id} | {msg.timestamp.strftime('%Y-%m-%d %H:%M')}")
            output_lines.append("")

            # Include surrounding messages for context
            for offset in (-1, 0, 1):
                j = idx + offset
                if 0 <= j < len(all_messages):
                    _, ctx_msg = all_messages[j]
                    if ctx_msg.role in ("user", "assistant") and ctx_msg.content:
                        marker = " **" if offset == 0 else ""
                        end_marker = "**" if offset == 0 else ""
                        role_label = ctx_msg.role.upper()
                        # Truncate long messages
                        content = ctx_msg.content[:300] + ("..." if len(ctx_msg.content) > 300 else "")
                        output_lines.append(f"{marker}{role_label}: {content}{end_marker}")

            output_lines.append("---")

        return ToolResult(
            tool_call_id="",
            content="\n".join(output_lines),
            is_error=False,
        )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/adapters/tools/test_search_history.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add squidbot/adapters/tools/search_history.py tests/adapters/tools/test_search_history.py
git commit -m "feat(tools): add search_history tool for episodic memory across sessions"
```

---

## Task 2: Add config and wire into ToolRegistry

**Files:**
- Modify: `squidbot/config/schema.py`
- Modify: `squidbot/adapters/tools/__init__.py`
- Modify: `squidbot/cli/main.py`

**Step 1: Add config class**

In `squidbot/config/schema.py`, add before `ToolsConfig`:

```python
class SearchHistoryConfig(BaseModel):
    """Configuration for the search_history tool."""

    enabled: bool = True
```

In `ToolsConfig`, add:

```python
search_history: SearchHistoryConfig = Field(default_factory=SearchHistoryConfig)
```

**Step 2: Export in `__init__.py`**

In `squidbot/adapters/tools/__init__.py`, add import:

```python
from squidbot.adapters.tools.search_history import SearchHistoryTool
```

**Step 3: Wire in `cli/main.py`**

Find where tools are registered in `_make_agent_loop()`. Add:

```python
if settings.tools.search_history.enabled:
    from squidbot.adapters.tools.search_history import SearchHistoryTool
    registry.register(SearchHistoryTool(base_dir=base_dir))
```

**Step 4: Run all tests**

```bash
uv run pytest -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add squidbot/config/schema.py squidbot/adapters/tools/__init__.py squidbot/cli/main.py
git commit -m "feat(config): wire search_history tool into registry with enabled flag"
```

---

## Task 3: Update README

**Files:**
- Modify: `README.md`

**Step 1: Add to tools config example**

```yaml
tools:
  search_history:
    enabled: true    # default: true
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document search_history tool in README config example"
```

---

## Verification

```bash
uv run pytest -v
uv run ruff check .
uv run mypy squidbot/
```

All must pass before considering this feature complete.
