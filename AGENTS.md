# squidbot — Agent Coding Guide

## Commands

```bash
# Install dependencies (including dev)
uv sync

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/core/test_agent.py -v

# Run a single test by name
uv run pytest tests/core/test_agent.py::test_simple_text_response -v

# Run a single test class
uv run pytest tests/adapters/channels/test_rich_cli.py::TestRichCliChannelSend -v

# Lint (must pass before committing)
uv run ruff check .

# Format
uv run ruff format .

# Type-check
uv run mypy squidbot/

# Install/update CLI tool after code changes (--reinstall required; --force is not enough)
uv tool install --reinstall /home/alex/git/squidbot
```

**Always run `uv run ruff check .` and `uv run pytest` before committing.**

**Use Conventional Commits:** `type(scope): description` — types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `deps`. Examples: `feat: add RichCliChannel`, `fix: handle KeyboardInterrupt in _prompt`, `deps: add rich as explicit dependency`.

**GPG signing is enabled globally (`commit.gpgsign=true`). Never use `--no-gpg-sign`. Commits without a signature are a bug.** Simply run `git commit -m "..."` — signing happens automatically.

---

## Architecture — Hexagonal (Ports & Adapters)

```
squidbot/
├── core/           # Domain logic — NO imports from adapters/
│   ├── models.py   # Pure dataclasses (Message, Session, CronJob, ToolCall, …)
│   ├── ports.py    # Protocol interfaces (LLMPort, ChannelPort, ToolPort, …)
│   ├── agent.py    # AgentLoop: orchestrates LLM + tools + memory + channel
│   ├── memory.py   # MemoryManager: history, memory.md, skills injection
│   ├── registry.py # ToolRegistry: register and dispatch tools
│   ├── scheduler.py# CronScheduler: schedule parsing and background loop
│   └── skills.py   # SkillMetadata dataclass + build_skills_xml()
├── adapters/       # Concrete implementations of ports
│   ├── llm/        # OpenAIAdapter
│   ├── channels/   # CliChannel, RichCliChannel
│   ├── persistence/# JsonlMemory
│   ├── tools/      # file, shell, memory_write tools
│   └── skills/     # FsSkillsLoader
├── config/         # Pydantic Settings (schema.py)
├── cli/            # CLI entry point (main.py, cyclopts)
└── skills/         # Bundled SKILL.md files shipped with the package

tests/
├── core/           # Pure unit tests — no network, no real FS (use tmp_path)
├── adapters/       # Adapter tests using unittest.mock
└── integration/    # Placeholder (empty)
```

**Core rule:** `squidbot/core/` never imports from `squidbot/adapters/`. The dependency
direction is `CLI/Adapters → Ports ← Core`. Adapters satisfy protocols structurally
(duck typing) — no inheritance from Port classes.

**Composition root:** `cli/main.py::_make_agent_loop()` — all adapter construction and
wiring happens here. Adapters are imported lazily inside `async def` helpers to keep
the import graph clean and startup fast.

---

## Code Style

- **Line length:** 100 characters
- **Formatter:** `ruff format` (replaces black)
- **Linter rules:** `E, F, I, UP, B, SIM` (see `pyproject.toml`)
- **Python version:** 3.14 (`requires-python = ">=3.14"`, `target-version = "py314"`)

---

## Imports

```python
# Every production file starts with this
from __future__ import annotations

# Import order (enforced by ruff I / isort):
# 1. stdlib
# 2. third-party
# 3. first-party (squidbot.*)

# Always use absolute imports — no relative imports
from squidbot.core.models import InboundMessage, Session

# Prefer collections.abc over typing for generics (ruff UP enforces this)
from collections.abc import AsyncIterator

# Deferred / lazy imports inside functions are acceptable to avoid circular deps
# or to keep CLI startup fast — suppress with # noqa: PLC0415 if ruff complains
```

---

## Type Annotations

- Annotate **all** function signatures, return types, and instance attributes.
- `mypy --strict` is enabled — all code must pass without errors.
- Use modern union syntax: `str | None` not `Optional[str]`.
- Use `Protocol` for ports (structural subtyping); adapters do **not** inherit from ports.
- `# type: ignore[assignment]` is acceptable in tests when assigning incomplete mocks.
- Use `dict[str, Any]` and `list[Any]` for inherently untyped JSON-shaped data.
- Use `TYPE_CHECKING` blocks for annotations that would create circular imports or
  runtime cost — safe because `from __future__ import annotations` makes all annotations
  lazy strings. Example: `if TYPE_CHECKING: from squidbot.core.ports import ChannelPort`.
- Known pyright false positives exist for async generator protocols — do not attempt
  to fix LSP errors that do not appear in `mypy` or `ruff`.
- `ChannelPort.receive()` is `def` (not `async def`) returning `AsyncIterator` — the
  concrete implementations are async generator functions, which return `AsyncIterator`
  directly when called (no `await` needed).

---

## Naming

| Thing | Convention | Example |
|---|---|---|
| Classes | `PascalCase` | `AgentLoop`, `JsonlMemory` |
| Port interfaces | `PascalCase` + `Port` suffix | `LLMPort`, `ChannelPort` |
| Functions / methods | `snake_case` | `build_messages`, `is_due` |
| Private helpers | `_leading_underscore` | `_format_llm_error` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_TOOL_ROUNDS` |
| Source files | `snake_case.py` | `memory_write.py` |
| Test files | `test_<module>.py` | `test_agent.py` |
| Test classes | `Test<Component><Aspect>` | `TestRichCliChannelSend` |
| Test doubles | Descriptive names | `ScriptedLLM`, `CollectingChannel` |

---

## Docstrings

- **Every module** gets a top-level docstring (2–5 sentences, purpose + architectural role).
- **All public classes and methods** get docstrings.
- **Style:** Google format — `Args:` / `Returns:` sections with indented descriptions.
- No `Raises:` sections — errors are returned as values, not raised (see below).
- Private helpers: single-line docstring is fine.

```python
async def chat(self, messages: list[Message], tools: list[ToolDefinition]) -> ...:
    """
    Send messages to the LLM and receive a response stream.

    Args:
        messages: Full conversation history including system prompt.
        tools: Available tool definitions in OpenAI format.
    """
```

---

## Error Handling

- **Tools return errors as values:** `ToolResult(is_error=True, content="Error: ...")`.
  Never raise from tool execution — the LLM sees the error as a tool response.
- **AgentLoop catches LLM exceptions** broadly and calls `_format_llm_error()` to produce
  a user-friendly message. Pattern-match on exception type name for known API errors.
- **Scheduler suppresses all errors** in `_tick()` — a failed cron job must not crash the loop.
- **Broad `except Exception as e`** is acceptable at adapter boundaries and scheduler ticks.
  Narrow exceptions are preferred everywhere else.
- **Multiple exceptions:** prefer the tuple form `except (EOFError, KeyboardInterrupt):` for
  readability. In Python 3.14+, the bare-comma form `except EOFError, KeyboardInterrupt:` is
  also valid and catches both exceptions — it is **not** a bug on this project. Do not flag
  or auto-fix it. (Note: in Python 2 and Python 3.0–3.13 the bare-comma form had different
  or invalid semantics; the equivalence was restored in 3.14.)

---

## Tests

- `asyncio_mode = "auto"` is set globally — `async def test_*` functions run without
  `@pytest.mark.asyncio`. Adding the decorator explicitly is also fine.
- **Core tests** (`tests/core/`) use hand-written in-memory doubles — no `unittest.mock`,
  no network, no real filesystem. Use `pytest`'s `tmp_path` fixture for FS tests.
- **Adapter tests** (`tests/adapters/`) use `unittest.mock.patch`, `MagicMock`, `AsyncMock`.
  Patch at the usage namespace: `patch("squidbot.adapters.channels.cli.Console")`.
- **TDD:** write the failing test first, verify it fails, then implement.
- **Test doubles** live in the test file that uses them — not in shared fixtures files.
- Tool tests call `await tool.execute(key=value)` — keyword args go straight into `**kwargs`.

---

## Logging (loguru)

- **Import:** `from loguru import logger` — no per-module `getLogger()` needed.
- **String formatting:** Use brace-style `{}` or f-strings — **not** `%s`/`%d` (those
  are not interpolated by loguru and will appear literally in output).
  - `logger.info("started (every {}m)", interval)` — correct, lazy
  - `logger.info(f"started (every {interval}m)")` — correct, eager
  - `logger.info("started (every %dm)", interval)` — **wrong**, prints literally
- **Test safety:** loguru has no sink by default in tests — all `logger.*` calls are no-ops.
- **Setup:** `_setup_logging(level)` in `cli/main.py` configures a stderr sink once at startup.

---

## Channel Streaming

`ChannelPort.streaming` controls how `AgentLoop` delivers responses:
- `streaming = True` (`CliChannel`): `send()` called per text chunk as it arrives.
- `streaming = False` (`RichCliChannel`, Matrix, Email): chunks accumulated, `send()` called
  once with complete text. Required for Markdown rendering.

---

## Tool Implementation Pattern

All tool `execute()` methods use `**kwargs: Any` to conform to `ToolPort`. Extract and
validate parameters internally:

```python
async def execute(self, **kwargs: Any) -> ToolResult:
    # Required string parameter
    val_raw = kwargs.get("param_name")
    if not isinstance(val_raw, str) or not val_raw:
        return ToolResult(tool_call_id="", content="Error: param_name is required", is_error=True)
    val: str = val_raw

    # Optional string parameter with default
    opt: str = kwargs.get("opt_param") if isinstance(kwargs.get("opt_param"), str) else "."

    # Optional int parameter with safe coercion
    try:
        count: int = int(kwargs.get("count", 5))
    except (TypeError, ValueError):
        count = 5
```

Always return `ToolResult(tool_call_id="", ...)` — `tool_call_id` is overwritten by
`ToolRegistry.dispatch()` with the real ID from the LLM call.

---

## MCP Servers

External MCP tools are wired in `_make_agent_loop()` via `McpServerConnection`. Each
server's tools become `McpToolAdapter` instances registered in `ToolRegistry`. Config
lives under `tools.mcp_servers` in `squidbot.yaml`. Two transports:
- `stdio`: spawns a subprocess (`command` + `args`)
- `http`: SSE endpoint (`url`)

`McpConnectionProtocol` is a small structural Protocol in `adapters/tools/mcp.py` that lets
`main.py` type the connection list without importing the concrete class.

---

## Deploying CLI Changes

`uv tool upgrade` and `uv tool install --force` do **not** re-copy source files when
the version string is unchanged. Always use:

```bash
uv tool install --reinstall /home/alex/git/squidbot
```
