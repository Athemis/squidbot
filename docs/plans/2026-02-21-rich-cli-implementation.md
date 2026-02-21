# Rich CLI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace bare `print()`-based CLI with Rich-powered interface: coloured prompts, Markdown rendering, and a startup banner.

**Architecture:** `RichCliChannel` is a new adapter class added to `squidbot/adapters/channels/cli.py` alongside the existing `CliChannel`. It satisfies `ChannelPort` structurally (no inheritance needed). `main.py` switches from `CliChannel` to `RichCliChannel` for the interactive `agent` command only; the gateway keeps `CliChannel`.

**Tech Stack:** Python 3.14, Rich (already installed transitively via `mcp`), uv for package management.

---

### Task 1: Add `rich` as explicit dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add `rich` to dependencies list**

In `pyproject.toml`, add `"rich>=13.0"` to the `dependencies` array after `cyclopts`:

```toml
dependencies = [
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "openai>=2.0",
    "httpx>=0.28",
    "matrix-nio>=0.25",
    "mcp>=1.0",
    "cyclopts>=3.0",
    "ruamel.yaml>=0.18",
    "cronsim>=2.0",
    "rich>=13.0",
]
```

**Step 2: Verify uv picks it up (dry-run)**

Run: `uv sync`
Expected: No errors, `rich` listed in resolved deps.

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add rich as explicit dependency"
```

---

### Task 2: Write failing test for `RichCliChannel`

**Files:**
- Create: `tests/adapters/channels/__init__.py` (empty)
- Create: `tests/adapters/__init__.py` (empty)
- Create: `tests/adapters/channels/test_rich_cli.py`

**Step 1: Create `__init__.py` files**

Create `tests/adapters/__init__.py` — empty file.
Create `tests/adapters/channels/__init__.py` — empty file.

**Step 2: Write failing test**

Create `tests/adapters/channels/test_rich_cli.py`:

```python
"""Tests for RichCliChannel."""

from __future__ import annotations

from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from squidbot.adapters.channels.cli import RichCliChannel
from squidbot.core.models import OutboundMessage, Session


class TestRichCliChannelAttributes:
    def test_streaming_is_false(self):
        """RichCliChannel must not stream — Markdown needs the full text."""
        ch = RichCliChannel()
        assert ch.streaming is False

    def test_session_is_cli_local(self):
        ch = RichCliChannel()
        assert ch.SESSION == Session(channel="cli", sender_id="local")


class TestRichCliChannelSend:
    @pytest.mark.asyncio
    async def test_send_prints_to_console(self):
        """send() should call Console.print with a Markdown object."""
        ch = RichCliChannel()
        msg = OutboundMessage(session=Session(channel="cli", sender_id="local"), text="**hello**")

        with patch("squidbot.adapters.channels.cli.Console") as MockConsole:
            mock_console = MagicMock()
            MockConsole.return_value = mock_console

            await ch.send(msg)

            mock_console.print.assert_called_once()
            # The argument should contain the text somewhere
            call_args = mock_console.print.call_args
            assert call_args is not None

    @pytest.mark.asyncio
    async def test_send_typing_is_noop(self):
        """send_typing() should not raise."""
        ch = RichCliChannel()
        await ch.send_typing("cli:local")  # Should not raise


class TestRichCliChannelReceive:
    @pytest.mark.asyncio
    async def test_receive_yields_inbound_message(self):
        """receive() should yield an InboundMessage for non-empty, non-exit input."""
        ch = RichCliChannel()

        with patch("squidbot.adapters.channels.cli.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            # First call returns a message, second raises EOFError to end the loop
            mock_thread.side_effect = ["Hello world", EOFError()]

            messages = []
            async for msg in ch.receive():
                messages.append(msg)

        assert len(messages) == 1
        assert messages[0].text == "Hello world"

    @pytest.mark.asyncio
    async def test_receive_skips_empty_input(self):
        """receive() should skip blank lines."""
        ch = RichCliChannel()

        with patch("squidbot.adapters.channels.cli.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.side_effect = ["   ", "Hi", EOFError()]

            messages = []
            async for msg in ch.receive():
                messages.append(msg)

        assert len(messages) == 1
        assert messages[0].text == "Hi"

    @pytest.mark.asyncio
    async def test_receive_stops_on_exit(self):
        """receive() should stop when user types 'exit'."""
        ch = RichCliChannel()

        with patch("squidbot.adapters.channels.cli.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.side_effect = ["exit"]

            messages = []
            async for msg in ch.receive():
                messages.append(msg)

        assert messages == []
```

**Step 3: Run tests to confirm they fail**

Run: `pytest tests/adapters/channels/test_rich_cli.py -v`
Expected: `ImportError: cannot import name 'RichCliChannel' from 'squidbot.adapters.channels.cli'`

---

### Task 3: Implement `RichCliChannel`

**Files:**
- Modify: `squidbot/adapters/channels/cli.py`

**Step 1: Add imports and implement `RichCliChannel`**

Append to `squidbot/adapters/channels/cli.py` after the existing `CliChannel` class:

```python
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.rule import Rule


class RichCliChannel:
    """
    Rich-powered CLI channel for interactive terminal use.

    Uses Rich for coloured prompts, Markdown rendering, and visual separators.
    streaming = False so the agent loop collects all chunks before calling send().
    """

    SESSION = Session(channel="cli", sender_id="local")
    streaming = False  # collect all chunks, then render Markdown once

    async def receive(self) -> AsyncIterator[InboundMessage]:
        """Yield messages from stdin using a coloured Rich prompt."""
        while True:
            try:
                line = await asyncio.to_thread(self._prompt)
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
        console = Console()
        console.print(Rule(style="dim"))
        try:
            return Prompt.ask("[bold green]You[/bold green]")
        except EOFError:
            return None

    async def send(self, message: OutboundMessage) -> None:
        """Render the response as Markdown using Rich."""
        console = Console()
        console.print("[bold cyan]squidbot ›[/bold cyan]")
        console.print(Markdown(message.text))

    async def send_typing(self, session_id: str) -> None:
        """No typing indicator for CLI."""
        pass
```

> **Note:** The `from rich.*` imports should go at the top of the file with the other imports, not inside the class. Move them to the top-level import block.

**Step 2: Run failing tests — they should now pass**

Run: `pytest tests/adapters/channels/test_rich_cli.py -v`
Expected: All 7 tests PASS.

**Step 3: Run full test suite — no regressions**

Run: `pytest -v`
Expected: All tests PASS.

**Step 4: Run ruff**

Run: `ruff check squidbot/adapters/channels/cli.py`
Expected: No errors.

**Step 5: Commit**

```bash
git add squidbot/adapters/channels/cli.py tests/adapters/
git commit -m "feat: add RichCliChannel with Markdown rendering and coloured prompts"
```

---

### Task 4: Update `main.py` — startup banner and switch to `RichCliChannel`

**Files:**
- Modify: `squidbot/cli/main.py`

**Step 1: Update `_run_agent()` to use `RichCliChannel` and print startup banner**

Replace the `_run_agent` function in `squidbot/cli/main.py`:

```python
async def _run_agent(message: str | None, config_path: Path) -> None:
    """Run the CLI channel agent."""
    from rich.console import Console
    from rich.rule import Rule

    from squidbot.adapters.channels.cli import CliChannel, RichCliChannel

    settings = Settings.load(config_path)
    agent_loop = await _make_agent_loop(settings)

    if message:
        # Single-shot mode: use plain CliChannel (streaming, no banner)
        channel = CliChannel()
        await agent_loop.run(CliChannel.SESSION, message, channel)
        print()  # newline after streamed output
        return

    # Interactive REPL mode: Rich interface
    console = Console()
    console.print(
        f"[bold]squidbot[/bold] 0.1.0  •  model: [cyan]{settings.llm.model}[/cyan]"
    )
    console.print(Rule(style="dim"))
    console.print("[dim]type 'exit' or Ctrl+D to quit[/dim]")

    channel = RichCliChannel()
    async for inbound in channel.receive():
        await agent_loop.run(inbound.session, inbound.text, channel)
```

**Step 2: Run ruff**

Run: `ruff check squidbot/cli/main.py`
Expected: No errors.

**Step 3: Run full test suite — no regressions**

Run: `pytest -v`
Expected: All tests PASS.

**Step 4: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "feat: use RichCliChannel and show startup banner in agent command"
```

---

### Task 5: Install and smoke-test

**Step 1: Upgrade the globally installed tool**

Run: `uv tool upgrade squidbot`
Expected: squidbot reinstalled with Rich.

**Step 2: Verify `squidbot --help` works**

Run: `squidbot --help`
Expected: Help text printed without errors.

**Step 3: Verify `squidbot agent --help` works**

Run: `squidbot agent --help`
Expected: Help text printed without errors.

**Step 4: Final test suite run**

Run: `pytest -v`
Expected: All tests PASS, 0 failures.

**Step 5: Final ruff run**

Run: `ruff check squidbot/`
Expected: No errors.
