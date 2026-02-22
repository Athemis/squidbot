# Contributing to squidbot

## Getting started

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo>
cd squidbot
uv sync                      # install dependencies including dev tools
uv run pytest                # all tests must pass
uv run ruff check .          # linter must be clean
uv run mypy squidbot/        # type checker must be clean
```

After changing source files, reinstall the CLI tool:

```bash
uv tool install --reinstall /path/to/squidbot
```

---

## Architecture

squidbot uses **Hexagonal Architecture (Ports & Adapters)**:

- `squidbot/core/` — domain logic. **Never imports from `squidbot/adapters/`.**
- `squidbot/adapters/` — concrete implementations of ports (LLM, channels, tools, persistence, skills).
- `squidbot/cli/main.py` — composition root. All adapter construction and wiring happens here.

Dependency direction: `CLI / Adapters → Ports ← Core`.

Adapters satisfy ports via structural subtyping (duck typing) — **do not inherit from Port classes**.

When adding a new adapter, implement the relevant `Protocol` from `core/ports.py` and wire it in `cli/main.py`.

---

## Code style

- **Line length:** 100 characters
- **Formatter:** `ruff format` — run before every commit
- **Linter:** `ruff check .` — rules `E, F, I, UP, B, SIM`
- **Python version:** 3.14 (`requires-python = ">=3.14"`)
- **Imports:** always absolute (`from squidbot.core.models import ...`), no relative imports
- **Generics:** use `collections.abc` over `typing` — `from collections.abc import AsyncIterator` not `from typing import AsyncIterator`
- **Union syntax:** `str | None` not `Optional[str]`
- **Lazy imports:** acceptable inside functions to avoid circular deps or speed up startup; suppress with `# noqa: PLC0415` if ruff complains

---

## Type annotations

- Annotate **all** function signatures, return types, and instance attributes
- `mypy --strict` is enabled — all code must pass without errors
- Use `Protocol` for ports; adapters do **not** inherit from ports
- Use `dict[str, Any]` and `list[Any]` for inherently untyped JSON-shaped data
- Use `TYPE_CHECKING` blocks for annotations that would create circular imports
- `# type: ignore[assignment]` is acceptable in tests when assigning incomplete mocks

---

## Naming conventions

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

- **Every module** gets a top-level docstring (2–5 sentences: purpose + architectural role)
- **All public classes and methods** get docstrings
- **Style:** Google format with `Args:` / `Returns:` sections

```python
async def chat(self, messages: list[Message], tools: list[ToolDefinition]) -> ...:
    """
    Send messages to the LLM and receive a response stream.

    Args:
        messages: Full conversation history including system prompt.
        tools: Available tool definitions in OpenAI format.
    """
```

- Private helpers: single-line docstring is fine
- No `Raises:` sections — errors are returned as values (see below)

---

## Testing

- **Write the failing test first**, verify it fails, then implement (TDD)
- `asyncio_mode = "auto"` — `async def test_*` functions run without `@pytest.mark.asyncio`
- **Core tests** (`tests/core/`) — hand-written in-memory doubles, no `unittest.mock`, no network, no real filesystem. Use `pytest`'s `tmp_path` for FS tests
- **Adapter tests** (`tests/adapters/`) — use `unittest.mock.patch`, `MagicMock`, `AsyncMock`. Patch at the usage namespace: `patch("squidbot.adapters.channels.cli.Console")`
- **Test doubles** live in the test file that uses them — not in shared fixture files
- Tool tests call `await tool.execute(key=value)` — keyword args go straight into `**kwargs`

```bash
uv run pytest                        # all tests
uv run pytest tests/core/ -v         # core unit tests only
uv run pytest tests/adapters/ -v     # adapter tests only
uv run pytest path/to/test.py::TestClass::test_name -v   # single test
```

---

## Error handling

- **Tools return errors as values:** `ToolResult(is_error=True, content="Error: ...")`. Never raise from tool execution — the LLM sees the error as a tool response
- **AgentLoop** catches LLM exceptions broadly and formats them for the user
- **Scheduler** suppresses all errors in `_tick()` — a failed cron job must not crash the loop
- Broad `except Exception as e` is acceptable at adapter boundaries and scheduler ticks; narrow exceptions preferred everywhere else

---

## Commits

squidbot uses **Conventional Commits**: `type(scope): description`

| Type | When |
|---|---|
| `feat` | new feature |
| `fix` | bug fix |
| `refactor` | code change that is neither feat nor fix |
| `test` | adding or updating tests |
| `docs` | documentation only |
| `chore` | tooling, deps, build |
| `deps` | dependency updates |

Examples: `feat: add RichCliChannel`, `fix: handle KeyboardInterrupt in _prompt`, `deps: add rich as explicit dependency`

**GPG signing** is enabled globally (`commit.gpgsign=true`). Run `git commit -m "..."` — signing happens automatically. **Never use `--no-gpg-sign`.**

---

## Pull requests

1. Branch from `main`
2. Make your changes with tests
3. Verify everything passes:
   ```bash
   uv run ruff check .
   uv run mypy squidbot/
   uv run pytest
   ```
4. Open a PR against `main` with:
   - A clear title following Conventional Commits style
   - A short summary of what changed and why
   - Any relevant context (linked issue, design decision, trade-off)

PRs with failing tests, linter errors, or mypy errors will not be merged.

---

## Reporting bugs

Please include:

- **Steps to reproduce** — minimal example or command that triggers the issue
- **Expected behaviour** — what you expected to happen
- **Actual behaviour** — what actually happened, including full error output
- **Environment** — Python version (`python --version`), squidbot version (`pip show squidbot`), OS
- **Config excerpt** — relevant parts of `squidbot.yaml` with secrets redacted

## Requesting features

Open an issue describing:

- **The problem** — what you're trying to do that isn't currently possible
- **Proposed solution** — how you'd like it to work (optional but helpful)
- **Alternatives considered** — other approaches you've thought of

Features that fit the hexagonal architecture and don't break the `core/` isolation principle are most likely to be accepted.
