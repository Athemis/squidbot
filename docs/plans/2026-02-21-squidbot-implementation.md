# squidbot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build squidbot — a lightweight personal AI assistant with hexagonal architecture, CLI/Matrix/Email channels, and a clean OpenAI-compatible LLM interface.

**Architecture:** Hexagonal (Ports & Adapters). The core domain (agent loop, memory, scheduler) uses only `Protocol` interfaces. Adapters implement those interfaces for LLM, channels, tools, and persistence. The core has zero external imports.

**Tech Stack:** Python 3.14, uv, pydantic v2, pydantic-settings, openai SDK, matrix-nio, httpx, cyclopts, ruamel.yaml, croniter, ruff, mypy, pytest, pytest-asyncio

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `squidbot/__init__.py`
- Create: `squidbot/core/__init__.py`
- Create: `squidbot/adapters/__init__.py`
- Create: `squidbot/adapters/llm/__init__.py`
- Create: `squidbot/adapters/channels/__init__.py`
- Create: `squidbot/adapters/tools/__init__.py`
- Create: `squidbot/adapters/persistence/__init__.py`
- Create: `squidbot/adapters/skills/__init__.py`
- Create: `squidbot/config/__init__.py`
- Create: `squidbot/cli/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/core/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `workspace/AGENTS.md`
- Create: `.gitignore`

**Step 1: Initialize uv project**

```bash
cd /home/alex/git/squidbot
uv init --name squidbot --python 3.14
```

**Step 2: Replace auto-generated pyproject.toml with complete version**

```toml
[project]
name = "squidbot"
version = "0.1.0"
description = "A lightweight personal AI assistant"
requires-python = ">=3.14"
dependencies = [
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "openai>=1.0",
    "httpx>=0.28",
    "matrix-nio>=0.25",
    "mcp>=1.0",
    "cyclopts>=3.0",
    "anyio>=4.0",
    "ruamel.yaml>=0.18",
    "croniter>=3.0",
]

[project.scripts]
squidbot = "squidbot.cli.main:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.9",
    "mypy>=1.13",
]

[tool.ruff]
target-version = "py314"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.mypy]
python_version = "3.14"
strict = true
```

**Step 3: Create package structure**

```bash
mkdir -p squidbot/core squidbot/adapters/llm squidbot/adapters/channels \
         squidbot/adapters/tools squidbot/adapters/persistence squidbot/adapters/skills \
         squidbot/config squidbot/cli squidbot/skills \
         tests/core tests/integration \
         workspace
touch squidbot/__init__.py squidbot/core/__init__.py \
      squidbot/adapters/__init__.py squidbot/adapters/llm/__init__.py \
      squidbot/adapters/channels/__init__.py squidbot/adapters/tools/__init__.py \
      squidbot/adapters/persistence/__init__.py squidbot/adapters/skills/__init__.py \
      squidbot/config/__init__.py squidbot/cli/__init__.py \
      tests/__init__.py tests/core/__init__.py tests/integration/__init__.py
```

**Step 4: Create workspace/AGENTS.md skeleton**

```markdown
# Agent Instructions

You are squidbot, a personal AI assistant.

## Memory

Your long-term memory is stored in `memory.md` (injected at session start).
When you learn something important about the user or their preferences,
use the `memory_write` tool to update your memory document.
Be selective: only record information that will be useful across sessions.

## Tools

You have access to tools for shell execution, file operations, web search, and more.
Use tools proactively when they would help the user.
Prefer minimal, targeted actions over broad ones.

## Communication

Be concise and direct. Show your work only when it adds value.
Prefer code and concrete output over lengthy explanations.
```

**Step 5: Create .gitignore**

```
__pycache__/
*.pyc
*.pyo
.venv/
dist/
*.egg-info/
.mypy_cache/
.ruff_cache/
.pytest_cache/
```

**Step 6: Install dependencies**

```bash
uv sync
```

Expected: All dependencies installed without error.

**Step 7: Commit**

```bash
git add .
git commit -m "chore: initial project scaffold"
```

---

## Task 2: Core Data Models

**Files:**
- Create: `squidbot/core/models.py`
- Create: `tests/core/test_models.py`

**Step 1: Write the failing tests**

```python
# tests/core/test_models.py
from datetime import datetime
from squidbot.core.models import Message, Session, CronJob, ToolCall, ToolDefinition

def test_message_basic():
    msg = Message(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"
    assert isinstance(msg.timestamp, datetime)

def test_message_with_tool_call():
    tool_call = ToolCall(id="tc_1", name="shell", arguments={"command": "ls"})
    msg = Message(role="assistant", content="", tool_calls=[tool_call])
    assert msg.tool_calls[0].name == "shell"

def test_session_id_format():
    session = Session(channel="cli", sender_id="local")
    assert session.id == "cli:local"

def test_cron_job_defaults():
    job = CronJob(id="j1", name="daily", message="good morning", schedule="0 9 * * *", channel="cli:local")
    assert job.enabled is True
    assert job.last_run is None
    assert job.timezone == "UTC"
    assert job.channel == "cli:local"

def test_tool_definition():
    tool = ToolDefinition(
        name="shell",
        description="Run a shell command",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    )
    assert tool.name == "shell"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_models.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'squidbot.core.models'"

**Step 3: Write the models**

```python
# squidbot/core/models.py
"""
Core data models for squidbot.

These are plain dataclasses and Pydantic models with no external dependencies
beyond the standard library and pydantic itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Any


@dataclass
class ToolCall:
    """A tool invocation requested by the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """The result of executing a tool."""
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    """A single message in a conversation."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None  # set when role == "tool"
    timestamp: datetime = field(default_factory=datetime.now)

    def to_openai_dict(self) -> dict[str, Any]:
        """Serialize to OpenAI API message format."""
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": str(tc.arguments)},
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d


@dataclass
class Session:
    """A conversation session, identified by channel and sender."""
    channel: str
    sender_id: str
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def id(self) -> str:
        return f"{self.channel}:{self.sender_id}"


@dataclass
class InboundMessage:
    """A message received from a channel."""
    session: Session
    text: str
    received_at: datetime = field(default_factory=datetime.now)


@dataclass
class OutboundMessage:
    """A message to be sent to a channel."""
    session: Session
    text: str


@dataclass
class ToolDefinition:
    """Definition of a tool that can be called by the LLM."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object

    def to_openai_dict(self) -> dict[str, Any]:
        """Serialize to OpenAI API tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class CronJob:
    """A scheduled task."""
    id: str
    name: str
    message: str
    schedule: str       # cron expression ("0 9 * * *") or interval ("every 3600")
    channel: str        # target session ID, e.g. "cli:local" or "matrix:@user:matrix.org"
    enabled: bool = True
    timezone: str = "UTC"
    last_run: datetime | None = None
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/core/test_models.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add squidbot/core/models.py tests/core/test_models.py
git commit -m "feat(core): add data models"
```

---

## Task 3: Port Interfaces

**Files:**
- Create: `squidbot/core/ports.py`
- Create: `tests/core/test_ports.py`

**Step 1: Write the failing tests**

The tests verify that the Protocols are correctly defined and that mock implementations
can satisfy them for use in core tests.

```python
# tests/core/test_ports.py
"""
Tests that mock adapters correctly satisfy the Port protocols.
This ensures our Protocol definitions are complete and usable.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from squidbot.core.models import Message, InboundMessage, OutboundMessage, ToolDefinition, ToolResult
from squidbot.core.ports import LLMPort, ChannelPort, ToolPort, MemoryPort


class MockLLM:
    """Minimal mock LLM that satisfies LLMPort."""
    async def chat(
        self, messages: list[Message], tools: list[ToolDefinition], *, stream: bool = True
    ) -> AsyncIterator[str]:
        async def _gen():
            yield "Hello, world!"
        return _gen()


class MockChannel:
    """Minimal mock channel that satisfies ChannelPort."""
    def __init__(self, messages: list[InboundMessage]):
        self._messages = messages

    async def receive(self) -> AsyncIterator[InboundMessage]:
        async def _gen():
            for m in self._messages:
                yield m
        return _gen()

    async def send(self, message: OutboundMessage) -> None:
        pass

    async def send_typing(self, session_id: str) -> None:
        pass


class MockTool:
    """Minimal mock tool that satisfies ToolPort."""
    name = "mock_tool"
    description = "A mock tool for testing"
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(tool_call_id="tc_1", content="mock result")


class MockMemory:
    """Minimal mock memory that satisfies MemoryPort."""
    async def load_history(self, session_id: str) -> list[Message]:
        return []

    async def append_message(self, session_id: str, message: Message) -> None:
        pass

    async def load_memory_doc(self, session_id: str) -> str:
        return ""

    async def save_memory_doc(self, session_id: str, content: str) -> None:
        pass


def test_mock_llm_satisfies_protocol():
    # runtime_checkable would require @runtime_checkable; we verify via mypy instead
    # This test just confirms the mock can be instantiated and typed correctly
    llm: LLMPort = MockLLM()  # type: ignore[assignment]
    assert llm is not None


def test_mock_channel_satisfies_protocol():
    channel: ChannelPort = MockChannel([])  # type: ignore[assignment]
    assert channel is not None


def test_mock_tool_satisfies_protocol():
    tool: ToolPort = MockTool()  # type: ignore[assignment]
    assert tool.name == "mock_tool"


def test_mock_memory_satisfies_protocol():
    memory: MemoryPort = MockMemory()  # type: ignore[assignment]
    assert memory is not None
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_ports.py -v
```

Expected: FAIL with "No module named 'squidbot.core.ports'"

**Step 3: Write the ports**

```python
# squidbot/core/ports.py
"""
Port interfaces for squidbot.

These are Python Protocol classes defining the contracts that adapters must satisfy.
The core domain imports ONLY from this file (and models.py) for any external dependency.

Adapters implement these protocols without inheriting from them (structural subtyping).
mypy verifies conformance statically.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from squidbot.core.models import (
    CronJob,
    InboundMessage,
    Message,
    OutboundMessage,
    ToolDefinition,
    ToolResult,
)


class LLMPort(Protocol):
    """
    Interface for language model communication.

    The LLM adapter wraps any OpenAI-compatible API endpoint.
    Responses are streamed as text chunks; tool calls are accumulated and
    returned as a structured event.
    """

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        stream: bool = True,
    ) -> AsyncIterator[str | list]:
        """
        Send messages to the LLM and receive a response stream.

        Yields either:
        - str: a text chunk to be forwarded to the channel
        - list[ToolCall]: a complete set of tool calls (end of response)

        Args:
            messages: The full conversation history including system prompt.
            tools: Available tool definitions in OpenAI format.
            stream: Whether to stream the response (default True).
        """
        ...


class ChannelPort(Protocol):
    """
    Interface for inbound/outbound message channels.

    A channel adapter handles the specifics of a messaging platform:
    authentication, message format conversion, and delivery.
    """

    async def receive(self) -> AsyncIterator[InboundMessage]:
        """Yield inbound messages as they arrive."""
        ...

    async def send(self, message: OutboundMessage) -> None:
        """Send a message to the channel."""
        ...

    async def send_typing(self, session_id: str) -> None:
        """
        Send a typing indicator if the channel supports it.

        Implementations that don't support typing indicators should no-op.
        """
        ...


class ToolPort(Protocol):
    """
    Interface for agent tools.

    Each tool exposes a name, description, and JSON Schema for its parameters.
    The agent loop calls execute() with parsed keyword arguments.
    """

    name: str
    description: str
    parameters: dict  # JSON Schema object describing accepted arguments

    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool with the given arguments.

        Args:
            **kwargs: Tool-specific arguments as defined in `parameters`.

        Returns:
            ToolResult with the output or error message.
        """
        ...


class MemoryPort(Protocol):
    """
    Interface for session state persistence.

    Manages two kinds of data:
    - Conversation history: JSONL log of all messages in a session
    - Memory document: agent-maintained markdown notes (memory.md)
    - Cron jobs: scheduled task definitions
    """

    async def load_history(self, session_id: str) -> list[Message]:
        """Load all messages for a session."""
        ...

    async def append_message(self, session_id: str, message: Message) -> None:
        """Append a single message to the session history."""
        ...

    async def load_memory_doc(self, session_id: str) -> str:
        """Load the agent's memory document for this session."""
        ...

    async def save_memory_doc(self, session_id: str, content: str) -> None:
        """Save the agent's memory document."""
        ...

    async def load_cron_jobs(self) -> list[CronJob]:
        """Load all scheduled jobs."""
        ...

    async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
        """Persist the full list of scheduled jobs."""
        ...
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/core/test_ports.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add squidbot/core/ports.py tests/core/test_ports.py
git commit -m "feat(core): add port interfaces"
```

---

## Task 4: JSONL Persistence Adapter

**Files:**
- Create: `squidbot/adapters/persistence/jsonl.py`
- Create: `tests/core/test_persistence.py`

**Step 1: Write the failing tests**

```python
# tests/core/test_persistence.py
import asyncio
import json
import tempfile
from pathlib import Path
import pytest
from squidbot.core.models import Message, CronJob
from squidbot.adapters.persistence.jsonl import JsonlMemory


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def memory(tmp_dir):
    return JsonlMemory(base_dir=tmp_dir)


@pytest.mark.asyncio
async def test_load_empty_history(memory):
    history = await memory.load_history("cli:local")
    assert history == []


@pytest.mark.asyncio
async def test_append_and_load_message(memory):
    msg = Message(role="user", content="hello")
    await memory.append_message("cli:local", msg)
    history = await memory.load_history("cli:local")
    assert len(history) == 1
    assert history[0].content == "hello"
    assert history[0].role == "user"


@pytest.mark.asyncio
async def test_multiple_messages_preserved_in_order(memory):
    msgs = [
        Message(role="user", content="first"),
        Message(role="assistant", content="second"),
        Message(role="user", content="third"),
    ]
    for m in msgs:
        await memory.append_message("cli:local", m)
    history = await memory.load_history("cli:local")
    assert [m.content for m in history] == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_memory_doc_empty_by_default(memory):
    doc = await memory.load_memory_doc("cli:local")
    assert doc == ""


@pytest.mark.asyncio
async def test_memory_doc_save_and_load(memory):
    await memory.save_memory_doc("cli:local", "# Notes\n- User prefers short responses")
    doc = await memory.load_memory_doc("cli:local")
    assert "prefers short responses" in doc


@pytest.mark.asyncio
async def test_cron_jobs_empty_by_default(memory):
    jobs = await memory.load_cron_jobs()
    assert jobs == []


@pytest.mark.asyncio
async def test_cron_jobs_save_and_load(memory):
    job = CronJob(id="j1", name="morning", message="Good morning!", schedule="0 9 * * *", channel="cli:local")
    await memory.save_cron_jobs([job])
    loaded = await memory.load_cron_jobs()
    assert len(loaded) == 1
    assert loaded[0].name == "morning"
    assert loaded[0].schedule == "0 9 * * *"
    assert loaded[0].channel == "cli:local"


@pytest.mark.asyncio
async def test_sessions_are_isolated(memory):
    await memory.append_message("cli:local", Message(role="user", content="session A"))
    await memory.append_message("matrix:user", Message(role="user", content="session B"))
    cli_history = await memory.load_history("cli:local")
    matrix_history = await memory.load_history("matrix:user")
    assert len(cli_history) == 1
    assert cli_history[0].content == "session A"
    assert len(matrix_history) == 1
    assert matrix_history[0].content == "session B"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_persistence.py -v
```

Expected: FAIL with "No module named 'squidbot.adapters.persistence.jsonl'"

**Step 3: Write the adapter**

```python
# squidbot/adapters/persistence/jsonl.py
"""
JSONL-based persistence adapter.

Stores conversation history as JSONL files (one message per line) and
memory documents as plain markdown files. Cron jobs are stored in a single
JSON file.

Directory layout:
    <base_dir>/
    ├── sessions/
    │   └── <session-id>.jsonl    # conversation history
    ├── memory/
    │   └── <session-id>/
    │       └── memory.md         # agent-maintained notes
    └── cron/
        └── jobs.json             # scheduled task list
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from squidbot.core.models import CronJob, Message, ToolCall


def _serialize_message(message: Message) -> str:
    """Serialize a Message to a JSON line."""
    d = {
        "role": message.role,
        "content": message.content,
        "timestamp": message.timestamp.isoformat(),
    }
    if message.tool_calls:
        d["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in message.tool_calls
        ]
    if message.tool_call_id:
        d["tool_call_id"] = message.tool_call_id
    return json.dumps(d)


def _deserialize_message(line: str) -> Message:
    """Deserialize a JSON line to a Message."""
    d = json.loads(line)
    tool_calls = None
    if "tool_calls" in d:
        tool_calls = [
            ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
            for tc in d["tool_calls"]
        ]
    return Message(
        role=d["role"],
        content=d.get("content", ""),
        tool_calls=tool_calls,
        tool_call_id=d.get("tool_call_id"),
        timestamp=datetime.fromisoformat(d["timestamp"]),
    )


def _session_file(base_dir: Path, session_id: str) -> Path:
    """Return the JSONL path for a session, creating parent directories."""
    # Replace ":" with "__" for safe filesystem paths
    safe_id = session_id.replace(":", "__")
    path = base_dir / "sessions" / f"{safe_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _memory_file(base_dir: Path, session_id: str) -> Path:
    """Return the memory.md path for a session."""
    safe_id = session_id.replace(":", "__")
    path = base_dir / "memory" / safe_id / "memory.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _cron_file(base_dir: Path) -> Path:
    """Return the cron jobs JSON path."""
    path = base_dir / "cron" / "jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class JsonlMemory:
    """
    Filesystem-based memory adapter using JSONL for history and JSON for jobs.

    All I/O is synchronous (no async file I/O library needed at this scale).
    Methods are async to satisfy the MemoryPort protocol.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    async def load_history(self, session_id: str) -> list[Message]:
        """Load all messages for a session from its JSONL file."""
        path = _session_file(self._base, session_id)
        if not path.exists():
            return []
        messages = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                messages.append(_deserialize_message(line))
        return messages

    async def append_message(self, session_id: str, message: Message) -> None:
        """Append a single message to the session's JSONL file."""
        path = _session_file(self._base, session_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(_serialize_message(message) + "\n")

    async def load_memory_doc(self, session_id: str) -> str:
        """Load the agent's memory document."""
        path = _memory_file(self._base, session_id)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    async def save_memory_doc(self, session_id: str, content: str) -> None:
        """Overwrite the agent's memory document."""
        path = _memory_file(self._base, session_id)
        path.write_text(content, encoding="utf-8")

    async def load_cron_jobs(self) -> list[CronJob]:
        """Load all scheduled jobs from the JSON file."""
        path = _cron_file(self._base)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        jobs = []
        for d in data:
            last_run = datetime.fromisoformat(d["last_run"]) if d.get("last_run") else None
            jobs.append(
                CronJob(
                    id=d["id"],
                    name=d["name"],
                    message=d["message"],
                    schedule=d["schedule"],
                    channel=d.get("channel", "cli:local"),
                    enabled=d.get("enabled", True),
                    timezone=d.get("timezone", "UTC"),
                    last_run=last_run,
                )
            )
        return jobs

    async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
        """Persist the full job list."""
        path = _cron_file(self._base)
        data = [
            {
                "id": j.id,
                "name": j.name,
                "message": j.message,
                "schedule": j.schedule,
                "channel": j.channel,
                "enabled": j.enabled,
                "timezone": j.timezone,
                "last_run": j.last_run.isoformat() if j.last_run else None,
            }
            for j in jobs
        ]
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/core/test_persistence.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add squidbot/adapters/persistence/jsonl.py tests/core/test_persistence.py
git commit -m "feat(adapters): add JSONL persistence adapter"
```

---

## Task 5: Configuration Schema

**Files:**
- Create: `squidbot/config/schema.py`
- Create: `tests/core/test_config.py`

**Step 1: Write the failing tests**

```python
# tests/core/test_config.py
import json
import os
import pytest
from pathlib import Path
from squidbot.config.schema import Settings, LLMConfig, ChannelConfig


def test_default_llm_config():
    cfg = LLMConfig()
    assert cfg.model == "anthropic/claude-opus-4-5"
    assert cfg.max_tokens == 8192
    assert cfg.max_context_tokens == 100_000


def test_settings_from_dict():
    raw = {
        "llm": {
            "api_base": "https://openrouter.ai/api/v1",
            "api_key": "sk-test",
            "model": "openai/gpt-4o",
        }
    }
    settings = Settings.model_validate(raw)
    assert settings.llm.api_key == "sk-test"
    assert settings.llm.model == "openai/gpt-4o"


def test_settings_loads_from_json_file(tmp_path):
    config = {"llm": {"api_key": "sk-from-file"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))
    settings = Settings.load(config_file)
    assert settings.llm.api_key == "sk-from-file"


def test_matrix_channel_disabled_by_default():
    settings = Settings()
    assert settings.channels.matrix.enabled is False


def test_email_channel_disabled_by_default():
    settings = Settings()
    assert settings.channels.email.enabled is False
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_config.py -v
```

Expected: FAIL with "No module named 'squidbot.config.schema'"

**Step 3: Write the config schema**

```python
# squidbot/config/schema.py
"""
Configuration schema for squidbot.

Settings are loaded from a JSON file (default: ~/.squidbot/config.json).
Individual fields can be overridden via environment variables using the
SQUIDBOT_ prefix (e.g., SQUIDBOT_LLM__API_KEY).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_CONFIG_PATH = Path.home() / ".squidbot" / "config.json"


class LLMConfig(BaseModel):
    """Configuration for the language model endpoint."""

    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "anthropic/claude-opus-4-5"
    max_tokens: int = 8192
    max_context_tokens: int = 100_000


class AgentConfig(BaseModel):
    """Configuration for agent behavior."""

    workspace: str = str(Path.home() / ".squidbot" / "workspace")
    system_prompt_file: str = "AGENTS.md"
    restrict_to_workspace: bool = True


class ShellToolConfig(BaseModel):
    enabled: bool = True


class WebSearchConfig(BaseModel):
    enabled: bool = False
    provider: str = "searxng"   # "searxng", "brave", "duckduckgo"
    url: str = ""
    api_key: str = ""


class ToolsConfig(BaseModel):
    shell: ShellToolConfig = Field(default_factory=ShellToolConfig)
    files: ShellToolConfig = Field(default_factory=ShellToolConfig)  # reuse enabled flag
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    mcp_servers: dict[str, Any] = Field(default_factory=dict)


class MatrixChannelConfig(BaseModel):
    enabled: bool = False
    homeserver: str = "https://matrix.org"
    user_id: str = ""
    access_token: str = ""
    device_id: str = "SQUIDBOT01"
    allow_from: list[str] = Field(default_factory=list)
    group_policy: str = "mention"   # "open", "mention", "allowlist"


class EmailChannelConfig(BaseModel):
    enabled: bool = False
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    from_address: str = ""
    allow_from: list[str] = Field(default_factory=list)
    tls_verify: bool = True
    use_tls: bool = True   # STARTTLS for SMTP


class ChannelsConfig(BaseModel):
    matrix: MatrixChannelConfig = Field(default_factory=MatrixChannelConfig)
    email: EmailChannelConfig = Field(default_factory=EmailChannelConfig)


class Settings(BaseModel):
    """Root configuration object for squidbot."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    agents: AgentConfig = Field(default_factory=AgentConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> "Settings":
        """
        Load settings from a JSON file.

        Missing keys use their default values.
        The file is optional — if it doesn't exist, all defaults apply.
        """
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def save(self, path: Path = DEFAULT_CONFIG_PATH) -> None:
        """Persist settings to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self.model_dump_json(indent=2, exclude_none=False),
            encoding="utf-8",
        )
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/core/test_config.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add squidbot/config/schema.py tests/core/test_config.py
git commit -m "feat(config): add configuration schema"
```

---

## Task 6: Core Memory Logic

**Files:**
- Create: `squidbot/core/memory.py`
- Create: `tests/core/test_memory.py`

**Step 1: Write the failing tests**

```python
# tests/core/test_memory.py
"""
Tests for the core memory manager.

Uses MockMemory (in-memory implementation) to test pruning logic
and memory.md injection without touching the filesystem.
"""
import pytest
from squidbot.core.models import Message
from squidbot.core.memory import MemoryManager


class InMemoryStorage:
    """Test double for MemoryPort — stores everything in RAM."""
    def __init__(self):
        self._histories: dict[str, list[Message]] = {}
        self._docs: dict[str, str] = {}

    async def load_history(self, session_id: str) -> list[Message]:
        return list(self._histories.get(session_id, []))

    async def append_message(self, session_id: str, message: Message) -> None:
        self._histories.setdefault(session_id, []).append(message)

    async def load_memory_doc(self, session_id: str) -> str:
        return self._docs.get(session_id, "")

    async def save_memory_doc(self, session_id: str, content: str) -> None:
        self._docs[session_id] = content

    async def load_cron_jobs(self):
        return []

    async def save_cron_jobs(self, jobs) -> None:
        pass


@pytest.fixture
def storage():
    return InMemoryStorage()


@pytest.fixture
def manager(storage):
    return MemoryManager(storage=storage, max_history_messages=5)


@pytest.mark.asyncio
async def test_build_messages_empty_session(manager):
    messages = await manager.build_messages(
        session_id="cli:local",
        system_prompt="You are a bot.",
        user_message="Hello",
    )
    # system + user = 2 messages
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[-1].role == "user"
    assert messages[-1].content == "Hello"


@pytest.mark.asyncio
async def test_build_messages_includes_memory_doc(manager, storage):
    await storage.save_memory_doc("cli:local", "User is a developer.")
    messages = await manager.build_messages(
        session_id="cli:local",
        system_prompt="You are a bot.",
        user_message="Hello",
    )
    # system prompt should include memory doc content
    assert "User is a developer." in messages[0].content


@pytest.mark.asyncio
async def test_build_messages_includes_history(manager, storage):
    await storage.append_message("cli:local", Message(role="user", content="prev"))
    await storage.append_message("cli:local", Message(role="assistant", content="response"))
    messages = await manager.build_messages(
        session_id="cli:local",
        system_prompt="You are a bot.",
        user_message="follow up",
    )
    # system + prev + response + follow up = 4
    assert len(messages) == 4


@pytest.mark.asyncio
async def test_prune_oldest_messages_when_over_limit(manager, storage):
    # Add 4 old messages (over the limit of 5)
    for i in range(6):
        await storage.append_message("cli:local", Message(role="user", content=f"msg {i}"))
    messages = await manager.build_messages(
        session_id="cli:local",
        system_prompt="You are a bot.",
        user_message="new",
    )
    # system + max_history (5) + new user = 7, but we prune to max_history_messages
    # so only 5 history messages kept (not 6)
    history_messages = [m for m in messages if m.role != "system"]
    assert len(history_messages) <= 5 + 1  # 5 history + 1 new user msg


@pytest.mark.asyncio
async def test_persist_exchange(manager, storage):
    await manager.persist_exchange(
        session_id="cli:local",
        user_message="Hello",
        assistant_reply="Hi there!",
    )
    history = await storage.load_history("cli:local")
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[1].role == "assistant"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_memory.py -v
```

Expected: FAIL with "No module named 'squidbot.core.memory'"

**Step 3: Write the memory manager**

```python
# squidbot/core/memory.py
"""
Core memory manager for squidbot.

Coordinates short-term (in-session history) and long-term (memory.md) memory.
The manager is pure domain logic — it takes a MemoryPort as dependency
and contains no I/O or external service calls.
"""

from __future__ import annotations

from squidbot.core.models import Message
from squidbot.core.ports import MemoryPort

# Injected into the system prompt when the context limit is approaching.
_PRUNE_WARNING = (
    "\n\n[System: Conversation history is long. Important information will be "
    "dropped soon. Use the memory_write tool to preserve anything critical before "
    "it leaves context.]\n"
)


class MemoryManager:
    """
    Manages message history and memory documents for agent sessions.

    Responsibilities:
    - Build the full message list for each LLM call (system + history + user)
    - Inject memory.md content into the system prompt
    - Prune old messages when history exceeds the configured limit
    - Persist new exchanges after each agent turn
    """

    def __init__(self, storage: MemoryPort, max_history_messages: int = 200) -> None:
        """
        Args:
            storage: The persistence adapter implementing MemoryPort.
            max_history_messages: Maximum number of history messages to keep.
                                  Older messages are dropped (not summarized).
        """
        self._storage = storage
        self._max_history = max_history_messages
        # Warn when we're 20% from the limit
        self._warn_threshold = int(max_history_messages * 0.8)

    async def build_messages(
        self,
        session_id: str,
        system_prompt: str,
        user_message: str,
    ) -> list[Message]:
        """
        Construct the full message list for an LLM call.

        Layout: [system_prompt + memory.md] + [history (pruned)] + [user_message]

        Args:
            session_id: Unique session identifier.
            system_prompt: The base system prompt (AGENTS.md content).
            user_message: The current user input.

        Returns:
            Ordered list of messages ready to send to the LLM.
        """
        memory_doc = await self._storage.load_memory_doc(session_id)
        history = await self._storage.load_history(session_id)

        # Build system prompt with memory document appended
        full_system = system_prompt
        if memory_doc.strip():
            full_system += f"\n\n## Your Memory\n\n{memory_doc}"

        # Prune history if over the limit
        near_limit = len(history) >= self._warn_threshold
        if len(history) > self._max_history:
            history = history[-self._max_history:]

        # Inject warning when approaching the limit
        if near_limit:
            full_system += _PRUNE_WARNING

        messages: list[Message] = [
            Message(role="system", content=full_system),
            *history,
            Message(role="user", content=user_message),
        ]
        return messages

    async def persist_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_reply: str,
    ) -> None:
        """
        Save a completed user–assistant exchange to history.

        Tool calls/results within the exchange are handled by the agent loop
        and appended separately via append_message.

        Args:
            session_id: Unique session identifier.
            user_message: The user's input text.
            assistant_reply: The final text response from the assistant.
        """
        await self._storage.append_message(
            session_id, Message(role="user", content=user_message)
        )
        await self._storage.append_message(
            session_id, Message(role="assistant", content=assistant_reply)
        )
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/core/test_memory.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add squidbot/core/memory.py tests/core/test_memory.py
git commit -m "feat(core): add memory manager"
```

---

## Task 7: OpenAI-Compatible LLM Adapter

**Files:**
- Create: `squidbot/adapters/llm/openai.py`

Note: No automated unit test for this adapter — it requires a live API call.
The adapter is tested via integration tests in `tests/integration/`.

**Step 1: Write the adapter**

```python
# squidbot/adapters/llm/openai.py
"""
OpenAI-compatible LLM adapter.

Works with any provider that exposes an OpenAI-compatible API:
OpenAI, Anthropic (via OpenRouter), local vLLM, LM Studio, etc.

The adapter streams responses and surfaces tool calls as structured events.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from squidbot.core.models import Message, ToolCall, ToolDefinition


class OpenAIAdapter:
    """
    LLM adapter for OpenAI-compatible endpoints.

    Implements LLMPort via structural subtyping (no explicit inheritance).
    """

    def __init__(self, api_base: str, api_key: str, model: str) -> None:
        """
        Args:
            api_base: Base URL for the API (e.g., "https://openrouter.ai/api/v1").
            api_key: API key for authentication.
            model: Model identifier (e.g., "anthropic/claude-opus-4-5").
        """
        self._client = AsyncOpenAI(base_url=api_base, api_key=api_key)
        self._model = model

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        stream: bool = True,
    ) -> AsyncIterator[str | list[ToolCall]]:
        """
        Send messages to the LLM and stream the response.

        Yields:
        - str chunks for text content (suitable for streaming to the user)
        - list[ToolCall] when the model requests tool execution (end of turn)
        """
        openai_messages = [m.to_openai_dict() for m in messages]
        openai_tools = [t.to_openai_dict() for t in tools] if tools else None

        if stream:
            return self._stream(openai_messages, openai_tools)
        else:
            return self._complete(openai_messages, openai_tools)

    async def _stream(
        self,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> AsyncIterator[str | list[ToolCall]]:
        """Stream response chunks and accumulate tool calls."""
        accumulated_tool_calls: dict[int, dict[str, Any]] = {}
        text_buffer = ""

        kwargs: dict[str, Any] = {"model": self._model, "messages": messages, "stream": True}
        if tools:
            kwargs["tools"] = tools

        async with await self._client.chat.completions.create(**kwargs) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                # Accumulate text
                if delta.content:
                    yield delta.content

                # Accumulate tool call fragments
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {
                                "id": tc_delta.id or "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc_delta.function:
                            if tc_delta.function.name:
                                accumulated_tool_calls[idx]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                accumulated_tool_calls[idx]["arguments"] += (
                                    tc_delta.function.arguments
                                )

        # Emit tool calls at the end of the stream
        if accumulated_tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    name=tc["name"],
                    arguments=json.loads(tc["arguments"]) if tc["arguments"] else {},
                )
                for tc in accumulated_tool_calls.values()
            ]
            yield tool_calls

    async def _complete(
        self,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> AsyncIterator[str | list[ToolCall]]:
        """Non-streaming completion (for sub-agents)."""
        kwargs: dict[str, Any] = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        if choice.message.content:
            yield choice.message.content

        if choice.message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments) if tc.function.arguments else {},
                )
                for tc in choice.message.tool_calls
            ]
            yield tool_calls
```

**Step 2: Commit**

```bash
git add squidbot/adapters/llm/openai.py
git commit -m "feat(adapters): add OpenAI-compatible LLM adapter"
```

---

## Task 8: Built-in Tools — Shell and Files

**Files:**
- Create: `squidbot/adapters/tools/shell.py`
- Create: `squidbot/adapters/tools/files.py`
- Create: `tests/core/test_tools.py`

**Step 1: Write the failing tests**

```python
# tests/core/test_tools.py
import pytest
from pathlib import Path
from squidbot.adapters.tools.shell import ShellTool
from squidbot.adapters.tools.files import ReadFileTool, WriteFileTool, ListFilesTool


@pytest.fixture
def tmp_workspace(tmp_path):
    return tmp_path


@pytest.mark.asyncio
async def test_shell_runs_command():
    tool = ShellTool(workspace=None, restrict_to_workspace=False)
    result = await tool.execute(command="echo hello")
    assert "hello" in result.content
    assert result.is_error is False


@pytest.mark.asyncio
async def test_shell_captures_stderr():
    tool = ShellTool(workspace=None, restrict_to_workspace=False)
    result = await tool.execute(command="ls /nonexistent_path_xyz")
    assert result.is_error is True


@pytest.mark.asyncio
async def test_read_file(tmp_workspace):
    (tmp_workspace / "test.txt").write_text("hello content")
    tool = ReadFileTool(workspace=tmp_workspace, restrict_to_workspace=True)
    result = await tool.execute(path="test.txt")
    assert "hello content" in result.content
    assert result.is_error is False


@pytest.mark.asyncio
async def test_read_file_outside_workspace_blocked(tmp_workspace):
    tool = ReadFileTool(workspace=tmp_workspace, restrict_to_workspace=True)
    result = await tool.execute(path="/etc/passwd")
    assert result.is_error is True
    assert "outside workspace" in result.content.lower()


@pytest.mark.asyncio
async def test_write_file(tmp_workspace):
    tool = WriteFileTool(workspace=tmp_workspace, restrict_to_workspace=True)
    result = await tool.execute(path="output.txt", content="written content")
    assert result.is_error is False
    assert (tmp_workspace / "output.txt").read_text() == "written content"


@pytest.mark.asyncio
async def test_list_files(tmp_workspace):
    (tmp_workspace / "a.txt").write_text("a")
    (tmp_workspace / "b.txt").write_text("b")
    tool = ListFilesTool(workspace=tmp_workspace, restrict_to_workspace=True)
    result = await tool.execute(path=".")
    assert "a.txt" in result.content
    assert "b.txt" in result.content
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_tools.py -v
```

Expected: FAIL with "No module named 'squidbot.adapters.tools.shell'"

**Step 3: Write the shell tool**

```python
# squidbot/adapters/tools/shell.py
"""
Shell command execution tool.

Runs shell commands via asyncio subprocess. When restrict_to_workspace
is True, the working directory is set to the workspace path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from squidbot.core.models import ToolDefinition, ToolResult


class ShellTool:
    """Executes shell commands, optionally scoped to the workspace directory."""

    name = "shell"
    description = (
        "Execute a shell command. Returns stdout and stderr combined. "
        "Use for running scripts, installing packages, or interacting with the system."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30).",
                "default": 30,
            },
        },
        "required": ["command"],
    }

    def __init__(self, workspace: Path | None, restrict_to_workspace: bool) -> None:
        self._workspace = workspace
        self._restrict = restrict_to_workspace

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def execute(self, command: str, timeout: int = 30, **_) -> ToolResult:
        """Run the command and return combined stdout/stderr."""
        cwd = str(self._workspace) if self._restrict and self._workspace else None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode(errors="replace")
            if proc.returncode != 0:
                return ToolResult(
                    tool_call_id="",
                    content=f"Exit code {proc.returncode}:\n{output}",
                    is_error=True,
                )
            return ToolResult(tool_call_id="", content=output)
        except TimeoutError:
            return ToolResult(
                tool_call_id="", content=f"Command timed out after {timeout}s", is_error=True
            )
        except Exception as e:
            return ToolResult(tool_call_id="", content=str(e), is_error=True)
```

**Step 4: Write the file tools**

```python
# squidbot/adapters/tools/files.py
"""
File operation tools: read, write, and list.

When restrict_to_workspace is True, all paths are resolved relative to
the workspace directory and path traversal outside it is blocked.
"""

from __future__ import annotations

from pathlib import Path

from squidbot.core.models import ToolDefinition, ToolResult


def _resolve_safe(workspace: Path, path: str, restrict: bool) -> Path | None:
    """
    Resolve a path. Returns None if the path escapes the workspace
    and restriction is enabled.
    """
    p = (workspace / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if restrict and not str(p).startswith(str(workspace.resolve())):
        return None
    return p


class ReadFileTool:
    """Read the contents of a file."""

    name = "read_file"
    description = "Read the contents of a file. Returns the file content as text."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read."},
        },
        "required": ["path"],
    }

    def __init__(self, workspace: Path, restrict_to_workspace: bool) -> None:
        self._workspace = workspace
        self._restrict = restrict_to_workspace

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(name=self.name, description=self.description, parameters=self.parameters)

    async def execute(self, path: str, **_) -> ToolResult:
        resolved = _resolve_safe(self._workspace, path, self._restrict)
        if resolved is None:
            return ToolResult(tool_call_id="", content="Error: path is outside workspace", is_error=True)
        if not resolved.exists():
            return ToolResult(tool_call_id="", content=f"Error: {path} does not exist", is_error=True)
        try:
            return ToolResult(tool_call_id="", content=resolved.read_text(encoding="utf-8"))
        except Exception as e:
            return ToolResult(tool_call_id="", content=str(e), is_error=True)


class WriteFileTool:
    """Write content to a file, creating it if it doesn't exist."""

    name = "write_file"
    description = "Write content to a file. Creates parent directories as needed."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to write."},
            "content": {"type": "string", "description": "Content to write."},
        },
        "required": ["path", "content"],
    }

    def __init__(self, workspace: Path, restrict_to_workspace: bool) -> None:
        self._workspace = workspace
        self._restrict = restrict_to_workspace

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(name=self.name, description=self.description, parameters=self.parameters)

    async def execute(self, path: str, content: str, **_) -> ToolResult:
        resolved = _resolve_safe(self._workspace, path, self._restrict)
        if resolved is None:
            return ToolResult(tool_call_id="", content="Error: path is outside workspace", is_error=True)
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return ToolResult(tool_call_id="", content=f"Written {len(content)} bytes to {path}")
        except Exception as e:
            return ToolResult(tool_call_id="", content=str(e), is_error=True)


class ListFilesTool:
    """List files in a directory."""

    name = "list_files"
    description = "List files and directories at the given path."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory to list (default: workspace root).", "default": "."},
        },
        "required": [],
    }

    def __init__(self, workspace: Path, restrict_to_workspace: bool) -> None:
        self._workspace = workspace
        self._restrict = restrict_to_workspace

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(name=self.name, description=self.description, parameters=self.parameters)

    async def execute(self, path: str = ".", **_) -> ToolResult:
        resolved = _resolve_safe(self._workspace, path, self._restrict)
        if resolved is None:
            return ToolResult(tool_call_id="", content="Error: path is outside workspace", is_error=True)
        if not resolved.is_dir():
            return ToolResult(tool_call_id="", content=f"Error: {path} is not a directory", is_error=True)
        entries = sorted(resolved.iterdir(), key=lambda p: (p.is_file(), p.name))
        lines = [f"{'d' if e.is_dir() else 'f'}  {e.name}" for e in entries]
        return ToolResult(tool_call_id="", content="\n".join(lines) if lines else "(empty)")
```

**Step 5: Run test to verify it passes**

```bash
uv run pytest tests/core/test_tools.py -v
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add squidbot/adapters/tools/shell.py squidbot/adapters/tools/files.py tests/core/test_tools.py
git commit -m "feat(adapters): add shell and file tools"
```

---

## Task 9: Core Tool Registry

**Files:**
- Create: `squidbot/core/registry.py`
- Create: `tests/core/test_registry.py`

**Step 1: Write the failing tests**

```python
# tests/core/test_registry.py
import pytest
from squidbot.core.models import ToolResult
from squidbot.core.registry import ToolRegistry


class EchoTool:
    name = "echo"
    description = "Echoes the input"
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, text: str, **_) -> ToolResult:
        return ToolResult(tool_call_id="", content=text)


def test_register_and_list():
    registry = ToolRegistry()
    registry.register(EchoTool())
    definitions = registry.get_definitions()
    assert len(definitions) == 1
    assert definitions[0].name == "echo"


@pytest.mark.asyncio
async def test_execute_known_tool():
    registry = ToolRegistry()
    registry.register(EchoTool())
    result = await registry.execute("echo", tool_call_id="tc_1", text="hello")
    assert result.content == "hello"
    assert result.tool_call_id == "tc_1"


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_error():
    registry = ToolRegistry()
    result = await registry.execute("unknown_tool", tool_call_id="tc_1")
    assert result.is_error is True
    assert "unknown_tool" in result.content
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_registry.py -v
```

Expected: FAIL with "No module named 'squidbot.core.registry'"

**Step 3: Write the registry**

```python
# squidbot/core/registry.py
"""
Tool registry for the agent loop.

Adapters register their tools here; the agent loop queries the registry
for available tool definitions and delegates execution to the correct tool.
"""

from __future__ import annotations

from squidbot.core.models import ToolDefinition, ToolResult
from squidbot.core.ports import ToolPort


class ToolRegistry:
    """Maintains a collection of tools and dispatches execution requests."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolPort] = {}

    def register(self, tool: ToolPort) -> None:
        """Register a tool. Raises ValueError on duplicate names."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get_definitions(self) -> list[ToolDefinition]:
        """Return OpenAI-format tool definitions for all registered tools."""
        return [
            ToolDefinition(
                name=t.name,
                description=t.description,
                parameters=t.parameters,
            )
            for t in self._tools.values()
        ]

    async def execute(self, tool_name: str, tool_call_id: str, **kwargs) -> ToolResult:
        """
        Execute a tool by name with the given arguments.

        Args:
            tool_name: Name of the tool to call.
            tool_call_id: The LLM-provided ID for this tool call.
            **kwargs: Tool-specific arguments.

        Returns:
            ToolResult with the output. Returns an error result if the tool
            is not found rather than raising an exception.
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                content=f"Error: unknown tool '{tool_name}'",
                is_error=True,
            )
        result = await tool.execute(**kwargs)
        result.tool_call_id = tool_call_id
        return result
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/core/test_registry.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add squidbot/core/registry.py tests/core/test_registry.py
git commit -m "feat(core): add tool registry"
```

---

## Task 10: Agent Loop

**Files:**
- Create: `squidbot/core/agent.py`
- Create: `tests/core/test_agent.py`

**Step 1: Write the failing tests**

```python
# tests/core/test_agent.py
"""
Tests for the agent loop using mock ports.

All external dependencies (LLM, channels, storage) are replaced with
in-memory test doubles. No network calls, no filesystem I/O.
"""
from __future__ import annotations

import asyncio
import pytest
from collections.abc import AsyncIterator

from squidbot.core.agent import AgentLoop
from squidbot.core.memory import MemoryManager
from squidbot.core.models import Message, ToolCall, ToolDefinition, ToolResult
from squidbot.core.registry import ToolRegistry


class ScriptedLLM:
    """LLM test double that returns pre-defined responses."""

    def __init__(self, responses: list[str | list[ToolCall]]):
        self._responses = iter(responses)

    async def chat(self, messages, tools, *, stream=True) -> AsyncIterator:
        response = next(self._responses)
        async def _gen():
            yield response
        return _gen()


class InMemoryStorage:
    def __init__(self):
        self._histories: dict[str, list[Message]] = {}
        self._docs: dict[str, str] = {}

    async def load_history(self, session_id):
        return list(self._histories.get(session_id, []))

    async def append_message(self, session_id, message):
        self._histories.setdefault(session_id, []).append(message)

    async def load_memory_doc(self, session_id):
        return self._docs.get(session_id, "")

    async def save_memory_doc(self, session_id, content):
        self._docs[session_id] = content

    async def load_cron_jobs(self):
        return []

    async def save_cron_jobs(self, jobs):
        pass


class EchoTool:
    name = "echo"
    description = "Echoes text"
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, text: str, **_) -> ToolResult:
        return ToolResult(tool_call_id="", content=f"echoed: {text}")


@pytest.fixture
def storage():
    return InMemoryStorage()


@pytest.fixture
def memory(storage):
    return MemoryManager(storage=storage, max_history_messages=100)


@pytest.mark.asyncio
async def test_simple_text_response(storage, memory):
    llm = ScriptedLLM(["Hello from the bot!"])
    registry = ToolRegistry()
    loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt="You are a bot.")

    response = await loop.run("cli:local", "Hello!")
    assert response == "Hello from the bot!"


@pytest.mark.asyncio
async def test_tool_call_then_text(storage, memory):
    tool_call = ToolCall(id="tc_1", name="echo", arguments={"text": "world"})
    llm = ScriptedLLM([[tool_call], "Result received!"])
    registry = ToolRegistry()
    registry.register(EchoTool())
    loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt="You are a bot.")

    response = await loop.run("cli:local", "Please echo world")
    assert "Result received!" in response


@pytest.mark.asyncio
async def test_history_persisted_after_run(storage, memory):
    llm = ScriptedLLM(["I remember you."])
    registry = ToolRegistry()
    loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt="You are a bot.")

    await loop.run("cli:local", "Remember me!")
    history = await storage.load_history("cli:local")
    assert len(history) == 2  # user + assistant
    assert history[0].role == "user"
    assert history[1].role == "assistant"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_agent.py -v
```

Expected: FAIL with "No module named 'squidbot.core.agent'"

**Step 3: Write the agent loop**

```python
# squidbot/core/agent.py
"""
Core agent loop for squidbot.

The agent loop coordinates the LLM, tool execution, and memory management.
It has no direct knowledge of channels, filesystems, or network protocols —
all external interactions happen through the injected port implementations.
"""

from __future__ import annotations

from squidbot.core.memory import MemoryManager
from squidbot.core.models import Message, ToolCall, ToolResult
from squidbot.core.ports import LLMPort
from squidbot.core.registry import ToolRegistry

# Maximum number of tool-call rounds per user message.
# Prevents infinite loops in case of buggy tool chains.
MAX_TOOL_ROUNDS = 20


class AgentLoop:
    """
    The core agent loop.

    For each user message, the loop:
    1. Builds the full message context (system + history + user)
    2. Calls the LLM
    3. If the LLM returns tool calls, executes them and loops back
    4. If the LLM returns text, persists the exchange and returns the text
    """

    def __init__(
        self,
        llm: LLMPort,
        memory: MemoryManager,
        registry: ToolRegistry,
        system_prompt: str,
    ) -> None:
        """
        Args:
            llm: The language model adapter.
            memory: The memory manager for history and memory.md.
            registry: The tool registry with all available tools.
            system_prompt: The base system prompt (AGENTS.md content).
        """
        self._llm = llm
        self._memory = memory
        self._registry = registry
        self._system_prompt = system_prompt

    async def run(self, session_id: str, user_message: str) -> str:
        """
        Process a single user message and return the assistant's reply.

        Args:
            session_id: Unique identifier for this conversation session.
            user_message: The user's input text.

        Returns:
            The assistant's final text response.
        """
        messages = await self._memory.build_messages(
            session_id=session_id,
            system_prompt=self._system_prompt,
            user_message=user_message,
        )
        tool_definitions = self._registry.get_definitions()

        final_text = ""
        tool_round = 0

        while tool_round < MAX_TOOL_ROUNDS:
            response_stream = await self._llm.chat(messages, tool_definitions)

            tool_calls: list[ToolCall] = []
            text_chunks: list[str] = []

            async for chunk in response_stream:
                if isinstance(chunk, str):
                    text_chunks.append(chunk)
                elif isinstance(chunk, list):
                    tool_calls = chunk

            text_response = "".join(text_chunks)
            if text_response:
                final_text = text_response

            if not tool_calls:
                # No tool calls — the agent is done
                break

            # Execute tool calls and append results to message history
            if text_response:
                messages.append(Message(role="assistant", content=text_response, tool_calls=tool_calls))
            else:
                messages.append(Message(role="assistant", content="", tool_calls=tool_calls))

            for tc in tool_calls:
                result = await self._registry.execute(tc.name, tool_call_id=tc.id, **tc.arguments)
                messages.append(
                    Message(
                        role="tool",
                        content=result.content,
                        tool_call_id=tc.id,
                    )
                )

            tool_round += 1
        else:
            final_text = final_text or "Error: maximum tool call rounds exceeded."

        # Persist the user message and final assistant reply
        await self._memory.persist_exchange(
            session_id=session_id,
            user_message=user_message,
            assistant_reply=final_text,
        )

        return final_text
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/core/test_agent.py -v
```

Expected: All tests PASS.

**Step 5: Run the full test suite**

```bash
uv run pytest tests/core/ -v
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add squidbot/core/agent.py tests/core/test_agent.py
git commit -m "feat(core): add agent loop"
```

---

## Task 11: CLI Channel Adapter + CLI Entry Point

**Files:**
- Create: `squidbot/adapters/channels/cli.py`
- Create: `squidbot/cli/main.py`

**Step 1: Write the CLI channel adapter**

```python
# squidbot/adapters/channels/cli.py
"""
Interactive CLI channel adapter.

Reads user input from stdin, sends responses to stdout.
Supports streaming output for a responsive feel.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator

from squidbot.core.models import InboundMessage, OutboundMessage, Session


class CliChannel:
    """
    CLI channel for interactive terminal use.

    The receive() method prompts for user input; send() prints to stdout.
    This adapter runs in a single session: "cli:local".
    """

    SESSION = Session(channel="cli", sender_id="local")

    async def receive(self) -> AsyncIterator[InboundMessage]:
        """Yield messages from stdin, one per line."""
        while True:
            try:
                loop = asyncio.get_event_loop()
                line = await loop.run_in_executor(None, self._prompt)
                if line is None:
                    break
                text = line.strip()
                if text.lower() in ("exit", "quit", "/exit", "/quit", ":q"):
                    break
                if text:
                    yield InboundMessage(session=self.SESSION, text=text)
            except (EOFError, KeyboardInterrupt):
                break

    def _prompt(self) -> str | None:
        """Blocking prompt — runs in a thread executor."""
        try:
            return input("\nYou: ")
        except EOFError:
            return None

    async def send(self, message: OutboundMessage) -> None:
        """Print the response to stdout."""
        print(f"\nAssistant: {message.text}")

    async def send_typing(self, session_id: str) -> None:
        """No typing indicator for CLI."""
        pass
```

**Step 2: Write the CLI entry point**

```python
# squidbot/cli/main.py
"""
CLI entry point for squidbot.

Commands:
  squidbot agent          Interactive chat (CLI channel)
  squidbot agent -m MSG   Single message mode
  squidbot gateway        Start gateway (all enabled channels)
  squidbot status         Show configuration and status
  squidbot onboard        Run interactive setup wizard
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import cyclopts

from squidbot.config.schema import DEFAULT_CONFIG_PATH, Settings

app = cyclopts.App(name="squidbot", help="A lightweight personal AI assistant.")


@app.command
def agent(
    message: str | None = None,
    config: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """
    Chat with the assistant.

    In interactive mode (no --message), starts a REPL loop.
    With --message, sends a single message and exits.
    """
    asyncio.run(_run_agent(message=message, config_path=config))


@app.command
def gateway(config: Path = DEFAULT_CONFIG_PATH) -> None:
    """Start the gateway (all enabled channels run concurrently)."""
    asyncio.run(_run_gateway(config_path=config))


@app.command
def status(config: Path = DEFAULT_CONFIG_PATH) -> None:
    """Show the current configuration and channel status."""
    settings = Settings.load(config)
    print(f"Model:   {settings.llm.model}")
    print(f"API:     {settings.llm.api_base}")
    print(f"Matrix:  {'enabled' if settings.channels.matrix.enabled else 'disabled'}")
    print(f"Email:   {'enabled' if settings.channels.email.enabled else 'disabled'}")
    print(f"Workspace: {settings.agents.workspace}")


@app.command
def onboard(config: Path = DEFAULT_CONFIG_PATH) -> None:
    """Run the interactive setup wizard."""
    asyncio.run(_run_onboard(config_path=config))


async def _make_agent_loop(settings: Settings):
    """Construct the agent loop from configuration."""
    from squidbot.adapters.llm.openai import OpenAIAdapter
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.adapters.tools.files import ListFilesTool, ReadFileTool, WriteFileTool
    from squidbot.adapters.tools.shell import ShellTool
    from squidbot.core.agent import AgentLoop
    from squidbot.core.memory import MemoryManager
    from squidbot.core.registry import ToolRegistry

    # Resolve workspace path
    workspace = Path(settings.agents.workspace).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)

    # Build storage directory
    storage_dir = Path.home() / ".squidbot"
    storage = JsonlMemory(base_dir=storage_dir)
    memory = MemoryManager(storage=storage, max_history_messages=200)

    # LLM adapter
    llm = OpenAIAdapter(
        api_base=settings.llm.api_base,
        api_key=settings.llm.api_key,
        model=settings.llm.model,
    )

    # Tool registry
    registry = ToolRegistry()
    restrict = settings.agents.restrict_to_workspace

    if settings.tools.shell.enabled:
        registry.register(ShellTool(workspace=workspace, restrict_to_workspace=restrict))
    registry.register(ReadFileTool(workspace=workspace, restrict_to_workspace=restrict))
    registry.register(WriteFileTool(workspace=workspace, restrict_to_workspace=restrict))
    registry.register(ListFilesTool(workspace=workspace, restrict_to_workspace=restrict))

    # Load system prompt
    system_prompt_path = workspace / settings.agents.system_prompt_file
    if system_prompt_path.exists():
        system_prompt = system_prompt_path.read_text(encoding="utf-8")
    else:
        system_prompt = "You are a helpful personal AI assistant."

    return AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt=system_prompt)


async def _run_agent(message: str | None, config_path: Path) -> None:
    """Run the CLI channel agent."""
    from squidbot.adapters.channels.cli import CliChannel

    settings = Settings.load(config_path)
    agent_loop = await _make_agent_loop(settings)
    channel = CliChannel()

    if message:
        # Single-shot mode
        reply = await agent_loop.run(CliChannel.SESSION.id, message)
        print(reply)
        return

    # Interactive REPL mode
    print("squidbot — type 'exit' or Ctrl+D to quit")
    async for inbound in channel.receive():
        reply = await agent_loop.run(inbound.session.id, inbound.text)
        await channel.send(
            from squidbot.core.models import OutboundMessage
            OutboundMessage(session=inbound.session, text=reply)
        )


async def _run_gateway(config_path: Path) -> None:
    """Start all enabled channels concurrently."""
    settings = Settings.load(config_path)
    agent_loop = await _make_agent_loop(settings)

    tasks = []

    # CLI is always available in gateway mode
    from squidbot.adapters.channels.cli import CliChannel
    from squidbot.core.models import OutboundMessage

    async def run_channel(channel):
        async for inbound in channel.receive():
            reply = await agent_loop.run(inbound.session.id, inbound.text)
            await channel.send(OutboundMessage(session=inbound.session, text=reply))

    tasks.append(asyncio.create_task(run_channel(CliChannel())))

    if tasks:
        await asyncio.gather(*tasks)


async def _run_onboard(config_path: Path) -> None:
    """Interactive setup wizard."""
    print("squidbot setup wizard")
    print("=" * 40)
    api_base = input("LLM API base URL [https://openrouter.ai/api/v1]: ").strip()
    api_key = input("API key: ").strip()
    model = input("Model [anthropic/claude-opus-4-5]: ").strip()

    settings = Settings()
    if api_base:
        settings.llm.api_base = api_base
    if api_key:
        settings.llm.api_key = api_key
    if model:
        settings.llm.model = model

    settings.save(config_path)
    print(f"\nConfiguration saved to {config_path}")
    print("Run 'squidbot agent' to start chatting!")


def main():
    app()


if __name__ == "__main__":
    main()
```

Note: The inline import in `_run_agent` needs to be fixed — move imports to top of async function.

**Step 3: Fix the import issue in _run_agent**

The `from squidbot.core.models import OutboundMessage` inside a f-string was a typo in the plan above. The correct implementation has it imported at the top of `_run_agent`.

**Step 4: Smoke test**

```bash
uv run squidbot status
```

Expected: Shows configuration values (with defaults since no config file exists yet).

**Step 5: Commit**

```bash
git add squidbot/adapters/channels/cli.py squidbot/cli/main.py
git commit -m "feat(cli): add CLI channel adapter and entry point"
```

---

## Task 12: Run Full Test Suite and Lint

**Step 1: Run all core tests**

```bash
uv run pytest tests/core/ -v
```

Expected: All tests PASS.

**Step 2: Run ruff linter**

```bash
uv run ruff check squidbot/
```

Fix any issues reported.

**Step 3: Run mypy**

```bash
uv run mypy squidbot/
```

Fix any type errors.

**Step 4: Commit any fixes**

```bash
git add -A
git commit -m "chore: fix lint and type errors"
```

---

## Task 13: Memory Write Tool

**Files:**
- Create: `squidbot/adapters/tools/memory_write.py`

The agent uses this tool to update its long-term memory document.

**Step 1: Write the tool**

```python
# squidbot/adapters/tools/memory_write.py
"""
Memory write tool — allows the agent to update its long-term memory document.
"""

from __future__ import annotations

from squidbot.core.models import ToolDefinition, ToolResult
from squidbot.core.ports import MemoryPort


class MemoryWriteTool:
    """
    Allows the agent to persist important information to its memory document.

    The memory document (memory.md) is injected into every system prompt,
    providing cross-session continuity for facts about the user's preferences,
    ongoing projects, and important context.
    """

    name = "memory_write"
    description = (
        "Update your long-term memory document. Use this to persist important "
        "information that should be available in future conversations: user preferences, "
        "ongoing projects, key facts. The content REPLACES the current memory document."
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The full new content for the memory document (Markdown).",
            },
        },
        "required": ["content"],
    }

    def __init__(self, storage: MemoryPort, session_id: str) -> None:
        self._storage = storage
        self._session_id = session_id

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def execute(self, content: str, **_) -> ToolResult:
        await self._storage.save_memory_doc(self._session_id, content)
        return ToolResult(tool_call_id="", content="Memory updated successfully.")
```

**Step 2: Commit**

```bash
git add squidbot/adapters/tools/memory_write.py
git commit -m "feat(adapters): add memory_write tool"
```

---

## Task 14: Cron Scheduler

**Files:**
- Create: `squidbot/core/scheduler.py`
- Create: `tests/core/test_scheduler.py`

**Step 1: Write the failing tests**

```python
# tests/core/test_scheduler.py
"""Tests for the cron scheduler."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import pytest
from squidbot.core.models import CronJob
from squidbot.core.scheduler import CronScheduler, parse_schedule, is_due


def test_parse_cron_expression():
    job = CronJob(id="1", name="test", message="hi", schedule="0 9 * * *", channel="cli:local")
    next_run = parse_schedule(job, now=datetime(2026, 2, 21, 8, 0, tzinfo=timezone.utc))
    assert next_run is not None
    assert next_run.hour == 9


def test_parse_interval():
    job = CronJob(id="1", name="test", message="hi", schedule="every 60", channel="cli:local")
    next_run = parse_schedule(job, now=datetime(2026, 2, 21, 8, 0, tzinfo=timezone.utc))
    assert next_run is not None


def test_is_due_past_time():
    job = CronJob(id="1", name="test", message="hi", schedule="0 9 * * *", channel="cli:local",
                  last_run=datetime(2026, 2, 21, 8, 0, tzinfo=timezone.utc))
    now = datetime(2026, 2, 21, 9, 1, tzinfo=timezone.utc)
    assert is_due(job, now=now)


def test_is_not_due_before_time():
    job = CronJob(id="1", name="test", message="hi", schedule="0 9 * * *", channel="cli:local")
    now = datetime(2026, 2, 21, 8, 59, tzinfo=timezone.utc)
    assert not is_due(job, now=now)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/core/test_scheduler.py -v
```

Expected: FAIL

**Step 3: Write the scheduler (minimal viable)**

Note: Use `croniter` or implement a simple cron parser. Add `croniter` to dependencies first:

```toml
# Add to pyproject.toml dependencies:
"croniter>=3.0",
```

```bash
uv add croniter
```

```python
# squidbot/core/scheduler.py
"""
Cron scheduler for recurring and one-time tasks.

Parses cron expressions ("0 9 * * *") and interval expressions ("every 3600").
The scheduler runs as a background asyncio task and triggers the agent loop
for each due job.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from croniter import croniter

from squidbot.core.models import CronJob
from squidbot.core.ports import MemoryPort

# Poll interval: check for due jobs every minute
POLL_INTERVAL_SECONDS = 60


def parse_schedule(job: CronJob, now: datetime | None = None) -> datetime | None:
    """
    Compute the next run time for a job.

    Supports:
    - Cron expressions: "0 9 * * *"
    - Interval expressions: "every N" (seconds)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    schedule = job.schedule.strip()
    if schedule.startswith("every "):
        try:
            seconds = int(schedule.split()[1])
            return now.replace(microsecond=0)
        except (IndexError, ValueError):
            return None

    try:
        cron = croniter(schedule, now)
        return cron.get_next(datetime)
    except Exception:
        return None


def is_due(job: CronJob, now: datetime | None = None) -> bool:
    """
    Return True if the job should run now.

    A job is due if its next scheduled time is <= now and it hasn't
    run in the current scheduling window.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if not job.enabled:
        return False

    schedule = job.schedule.strip()

    if schedule.startswith("every "):
        try:
            seconds = int(schedule.split()[1])
            if job.last_run is None:
                return True
            elapsed = (now - job.last_run).total_seconds()
            return elapsed >= seconds
        except (IndexError, ValueError):
            return False

    # Cron expression: check if we're past the next scheduled time since last run
    baseline = job.last_run or datetime(2000, 1, 1, tzinfo=timezone.utc)
    try:
        cron = croniter(schedule, baseline)
        next_run = cron.get_next(datetime)
        return next_run <= now
    except Exception:
        return False


class CronScheduler:
    """
    Background scheduler that polls for due jobs and triggers the agent.

    The scheduler loads jobs from storage, checks which are due, runs them
    via the provided callback, and updates last_run.
    """

    def __init__(self, storage: MemoryPort) -> None:
        self._storage = storage
        self._running = False

    async def run(self, on_due: callable) -> None:
        """
        Start the scheduler loop.

        Args:
            on_due: Async callback invoked with (job: CronJob) for each due job.
        """
        self._running = True
        while self._running:
            await self._tick(on_due)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _tick(self, on_due: callable) -> None:
        jobs = await self._storage.load_cron_jobs()
        now = datetime.now(timezone.utc)
        updated = False
        for job in jobs:
            if is_due(job, now=now):
                job.last_run = now
                updated = True
                try:
                    await on_due(job)
                except Exception:
                    pass  # Log in future; don't crash the scheduler
        if updated:
            await self._storage.save_cron_jobs(jobs)

    def stop(self) -> None:
        self._running = False
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/core/test_scheduler.py -v
```

Expected: All tests PASS.

**Step 5: Run all core tests**

```bash
uv run pytest tests/core/ -v
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add squidbot/core/scheduler.py tests/core/test_scheduler.py
git commit -m "feat(core): add cron scheduler"
```

---

## Task 15: Skills System — FsSkillsLoader and SkillsPort

**Files:**
- Create: `squidbot/core/skills.py`
- Create: `squidbot/adapters/skills/__init__.py`
- Create: `squidbot/adapters/skills/fs.py`
- Create: `tests/core/test_skills.py`

This task implements the skills infrastructure: the `SkillMetadata` model, the `SkillsPort`
protocol, and the `FsSkillsLoader` adapter (with mtime-based caching).

**Step 1: Add `SkillsPort` to ports.py**

Add to `squidbot/core/ports.py`:

```python
class SkillsPort(Protocol):
    """Interface for skill discovery and loading."""

    def list_skills(self) -> list["SkillMetadata"]: ...

    def load_skill_body(self, name: str) -> str:
        """Return the full SKILL.md text for a named skill."""
        ...
```

**Step 2: Write core/skills.py**

```python
# squidbot/core/skills.py
"""
Skills metadata model and XML summary builder.

The core domain only knows about SkillMetadata and the XML block format.
All filesystem I/O lives in the FsSkillsLoader adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring


@dataclass
class SkillMetadata:
    """Parsed metadata from a SKILL.md frontmatter block."""
    name: str
    description: str
    location: Path          # absolute path to SKILL.md
    always: bool = False    # inject full body into every system prompt
    available: bool = True  # False if required bins/env are missing
    requires_bins: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)
    emoji: str = ""


def build_skills_xml(skills: list[SkillMetadata]) -> str:
    """
    Build the <skills> XML block injected into the system prompt.

    Always-skills are excluded here — their full body is injected directly.
    """
    root = Element("skills")
    for skill in skills:
        if skill.always:
            continue  # injected as full body, not listed in XML
        el = SubElement(root, "skill", available=str(skill.available).lower())
        SubElement(el, "name").text = skill.name
        SubElement(el, "description").text = skill.description
        SubElement(el, "location").text = str(skill.location)
        if not skill.available:
            hints = []
            if skill.requires_bins:
                hints.append(f"CLI: {', '.join(skill.requires_bins)}")
            if skill.requires_env:
                hints.append(f"env: {', '.join(skill.requires_env)}")
            SubElement(el, "requires").text = "; ".join(hints)
    return tostring(root, encoding="unicode")
```

**Step 3: Write the FsSkillsLoader adapter**

```python
# squidbot/adapters/skills/fs.py
"""
Filesystem-based skills loader with mtime-based cache invalidation.

Searches skill directories in priority order:
  1. Extra dirs from config (highest priority)
  2. Workspace skills directory
  3. Bundled package skills (lowest priority)

Skills with the same name in a higher-priority directory shadow lower ones.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from squidbot.core.skills import SkillMetadata

_yaml = YAML()
_yaml.preserve_quotes = True


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    """Extract YAML frontmatter from a SKILL.md file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    yaml_block = text[3:end].strip()
    data = _yaml.load(yaml_block)
    return dict(data) if data else {}


def _check_availability(meta: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """
    Check whether a skill's requirements are satisfied.

    Returns (available, missing_bins, missing_env).
    """
    requires = meta.get("requires", {}) or {}
    bins = requires.get("bins", []) or []
    envs = requires.get("env", []) or []

    missing_bins = [b for b in bins if shutil.which(b) is None]
    missing_env = [e for e in envs if not os.environ.get(e)]

    available = not missing_bins and not missing_env
    return available, missing_bins, missing_env


class FsSkillsLoader:
    """
    Loads and caches skill metadata from SKILL.md files on the filesystem.

    Cache invalidation is mtime-based: if a SKILL.md's modification time
    changes, its entry is reloaded on the next list_skills() call.
    """

    def __init__(self, search_dirs: list[Path]) -> None:
        """
        Args:
            search_dirs: Ordered list of directories to search for skills.
                         Earlier entries take precedence over later ones.
        """
        self._search_dirs = search_dirs
        # Cache: path → (mtime, SkillMetadata)
        self._cache: dict[Path, tuple[float, SkillMetadata]] = {}

    def list_skills(self) -> list[SkillMetadata]:
        """
        Return all discovered skills, with higher-priority dirs shadowing lower ones.

        Skills are re-read from disk only if their mtime has changed.
        """
        seen: dict[str, SkillMetadata] = {}  # name → metadata (first-wins = highest priority)

        for search_dir in self._search_dirs:
            if not search_dir.is_dir():
                continue
            for skill_dir in sorted(search_dir.iterdir()):
                skill_file = skill_dir / "SKILL.md"
                if not skill_dir.is_dir() or not skill_file.exists():
                    continue
                name = skill_dir.name
                if name in seen:
                    continue  # already shadowed by higher-priority dir
                metadata = self._load_cached(skill_file, name)
                if metadata:
                    seen[name] = metadata

        return list(seen.values())

    def load_skill_body(self, name: str) -> str:
        """Return the full SKILL.md text for a named skill."""
        for search_dir in self._search_dirs:
            skill_file = search_dir / name / "SKILL.md"
            if skill_file.exists():
                return skill_file.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Skill '{name}' not found")

    def _load_cached(self, path: Path, name: str) -> SkillMetadata | None:
        """Load metadata from cache, re-reading from disk if mtime changed."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None

        if path in self._cache:
            cached_mtime, cached_meta = self._cache[path]
            if cached_mtime == mtime:
                return cached_meta

        # Cache miss or stale — parse from disk
        try:
            meta = _parse_frontmatter(path)
        except Exception:
            return None

        available, missing_bins, missing_env = _check_availability(meta)
        squidbot_meta = (meta.get("metadata") or {}).get("squidbot", {})

        skill = SkillMetadata(
            name=meta.get("name", name),
            description=meta.get("description", ""),
            location=path,
            always=bool(meta.get("always", False)),
            available=available,
            requires_bins=missing_bins,
            requires_env=missing_env,
            emoji=squidbot_meta.get("emoji", ""),
        )
        self._cache[path] = (mtime, skill)
        return skill
```

**Step 4: Write the failing tests**

```python
# tests/core/test_skills.py
"""Tests for the skills system."""
from __future__ import annotations

import pytest
from pathlib import Path
from squidbot.core.skills import SkillMetadata, build_skills_xml
from squidbot.adapters.skills.fs import FsSkillsLoader


@pytest.fixture
def skill_dir(tmp_path):
    """Create a temporary skills directory with one skill."""
    skill = tmp_path / "github"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: github\n"
        'description: "Interact with GitHub."\n'
        "always: false\n"
        "requires:\n"
        "  bins: []\n"
        "---\n\n# GitHub Skill\n\nDo stuff with GitHub.\n"
    )
    return tmp_path


def test_list_skills_discovers_skill(skill_dir):
    loader = FsSkillsLoader(search_dirs=[skill_dir])
    skills = loader.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "github"
    assert "GitHub" in skills[0].description


def test_load_skill_body(skill_dir):
    loader = FsSkillsLoader(search_dirs=[skill_dir])
    body = loader.load_skill_body("github")
    assert "GitHub Skill" in body


def test_mtime_cache(skill_dir):
    loader = FsSkillsLoader(search_dirs=[skill_dir])
    skills1 = loader.list_skills()
    skills2 = loader.list_skills()
    # Second call uses cache — same objects
    assert skills1[0].name == skills2[0].name


def test_higher_priority_dir_shadows_lower(tmp_path):
    low = tmp_path / "low"
    high = tmp_path / "high"
    for d in (low, high):
        skill = d / "github"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: github\ndescription: 'From {d.name}'\n---\n"
        )
    loader = FsSkillsLoader(search_dirs=[high, low])
    skills = loader.list_skills()
    assert len(skills) == 1
    assert "high" in skills[0].description


def test_always_skill_excluded_from_xml(skill_dir):
    (skill_dir / "memory").mkdir()
    (skill_dir / "memory" / "SKILL.md").write_text(
        "---\nname: memory\ndescription: 'Memory'\nalways: true\n---\n"
    )
    loader = FsSkillsLoader(search_dirs=[skill_dir])
    skills = loader.list_skills()
    xml = build_skills_xml(skills)
    assert "memory" not in xml  # always-skill excluded from XML listing
    assert "github" in xml


def test_unavailable_skill_shows_requires(tmp_path):
    skill = tmp_path / "gh-tool"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: gh-tool\ndescription: 'Needs gh'\nrequires:\n  bins: [__nonexistent_bin__]\n---\n"
    )
    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()
    assert skills[0].available is False
    xml = build_skills_xml(skills)
    assert 'available="false"' in xml
```

**Step 5: Run test to verify it fails**

```bash
uv run pytest tests/core/test_skills.py -v
```

Expected: FAIL with "No module named 'squidbot.core.skills'"

**Step 6: Install ruamel.yaml**

```bash
uv add "ruamel.yaml>=0.18"
```

**Step 7: Run test to verify it passes**

```bash
uv run pytest tests/core/test_skills.py -v
```

Expected: All tests PASS.

**Step 8: Add `squidbot skills list` command to CLI**

Add to `squidbot/cli/main.py`:

```python
skills_app = cyclopts.App(name="skills", help="Manage squidbot skills.")
app.command(skills_app)


@skills_app.command
def list(config: Path = DEFAULT_CONFIG_PATH) -> None:
    """List all discovered skills and their availability."""
    from squidbot.adapters.skills.fs import FsSkillsLoader

    settings = Settings.load(config)
    workspace = Path(settings.agents.workspace).expanduser()
    bundled = Path(__file__).parent.parent / "skills"

    extra_dirs = [Path(d).expanduser() for d in getattr(settings, "skills_extra_dirs", [])]
    search_dirs = extra_dirs + [workspace / "skills", bundled]

    loader = FsSkillsLoader(search_dirs=search_dirs)
    skills = loader.list_skills()

    if not skills:
        print("No skills found.")
        return

    for skill in sorted(skills, key=lambda s: s.name):
        status = "✓" if skill.available else "✗"
        always = " [always]" if skill.always else ""
        print(f"  {status}  {skill.name}{always}")
        print(f"     {skill.description}")
        if not skill.available:
            if skill.requires_bins:
                print(f"     requires: {', '.join(skill.requires_bins)}")
            if skill.requires_env:
                print(f"     env: {', '.join(skill.requires_env)}")
```

**Step 9: Commit**

```bash
git add squidbot/core/skills.py squidbot/adapters/skills/ tests/core/test_skills.py
git commit -m "feat(skills): add FsSkillsLoader with mtime cache and skills list command"
```

---

## Task 16: Final Integration — End-to-End Smoke Test

**Step 1: Run the full core test suite**

```bash
uv run pytest tests/core/ -v --tb=short
```

Expected: All tests PASS.

**Step 2: Ensure config exists**

Create `~/.squidbot/config.json` with real API credentials:

```json
{
  "llm": {
    "api_base": "https://openrouter.ai/api/v1",
    "api_key": "YOUR_KEY_HERE",
    "model": "anthropic/claude-opus-4-5"
  }
}
```

**Step 3: Run a single-shot agent message**

```bash
uv run squidbot agent -m "Say hello in one sentence."
```

Expected: A one-sentence greeting from the model.

**Step 5: Run linter and type checker**

```bash
uv run ruff check squidbot/ && uv run mypy squidbot/
```

Expected: No errors.

**Step 6: Commit final state**

```bash
git add -A
git commit -m "feat: complete initial implementation of squidbot core"
```

---

## Remaining Features (future tasks, not in scope for initial implementation)

After the above tasks are complete, the following can be added as separate tasks:

- **Matrix channel adapter** (`squidbot/adapters/channels/matrix.py`)
- **Email channel adapter** (`squidbot/adapters/channels/email.py`)
- **Web search tool** (`squidbot/adapters/tools/web_search.py`)
- **MCP client adapter** (`squidbot/adapters/tools/mcp.py`)
- **Sub-agent spawn tool** (`squidbot/adapters/tools/spawn.py`)
- **Cron CLI commands** (`cron list`, `cron add`, `cron remove`)
- **Integration tests** with live API
