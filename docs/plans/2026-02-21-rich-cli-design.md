# Rich CLI UX — Design

**Date:** 2026-02-21  
**Status:** Approved

## Goal

Replace the bare `print()`-based CLI with a polished Rich-powered interface:
coloured prompts, Markdown rendering, and a startup banner — without new dependencies.

## Decisions

| Topic | Decision |
|---|---|
| Library | Rich (already installed transitively via mcp) |
| Input | `rich.prompt.Prompt.ask()` — coloured prompt, readline support |
| Output | `rich.markdown.Markdown` — full Markdown + syntax highlighting |
| Streaming | `streaming = False` on `RichCliChannel` — chunks collected, rendered once |
| Style | Compact with colour — no panel boxes |

## Changes

### `squidbot/adapters/channels/cli.py`

New `RichCliChannel` class alongside the existing `CliChannel`:

- `streaming = False` — agent loop collects all chunks before calling `send()`
- `send()` renders the full reply via `Console().print(Markdown(text))`
- Prefixed with `[bold cyan]squidbot ›[/bold cyan]`
- `receive()` uses `Prompt.ask("[bold green]You[/bold green]")` for coloured input
- A thin `Rule()` is printed between turns
- Error messages rendered in `[bold red]`

### `squidbot/cli/main.py`

- Startup banner printed before the REPL loop:
  ```
  squidbot 0.1.0  •  model: anthropic/claude-opus-4-5
  ──────────────────────────────────────────────────
  type 'exit' or Ctrl+D to quit
  ```
- `_run_agent()` switches from `CliChannel` to `RichCliChannel`
- `rich` added as explicit dependency in `pyproject.toml`

## What Does Not Change

- Hexagonal architecture — `RichCliChannel` satisfies `ChannelPort` structurally
- All existing tests — they use `CollectingChannel`, not the CLI adapter
- `CliChannel` kept as-is (used in tests, gateway fallback)
