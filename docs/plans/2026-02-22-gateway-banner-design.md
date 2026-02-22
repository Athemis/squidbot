# Gateway Startup Banner Design

**Date:** 2026-02-22
**Status:** Approved

## Overview

Add a decorative startup banner to `squidbot gateway` that displays version, model, and
workspace info before the structured log output begins.

## Output

```
🦑 squidbot v0.1.0
   model:     anthropic/claude-opus-4-5
   workspace: /home/alex/squidbot-workspace
   ────────────────────────────────────────

2026-02-22 12:25:03 INFO     gateway starting
2026-02-22 12:25:03 INFO     matrix: disabled
...
```

## Implementation

A helper `_print_banner(settings: Settings) -> None` is added to `squidbot/cli/main.py`
and called at the top of `_run_gateway`, before any `logger.info` calls.

```python
def _print_banner(settings: Settings) -> None:
    import sys
    from importlib.metadata import version

    ver = version("squidbot")
    model = settings.llm.model
    workspace = Path(settings.agents.workspace).expanduser()
    print(f"🦑 squidbot v{ver}", file=sys.stderr)
    print(f"   model:     {model}", file=sys.stderr)
    print(f"   workspace: {workspace}", file=sys.stderr)
    print(f"   {'─' * 40}", file=sys.stderr)
    print(file=sys.stderr)
```

## Design Decisions

- **Plain `print(..., file=sys.stderr)`** — not loguru. A timestamp and `INFO` prefix
  in front of each banner line would break the visual effect.
- **Emoji:** `🦑` — matches the existing `squidbot agent` REPL banner in `_run_agent`.
- **Version:** `importlib.metadata.version("squidbot")` — always in sync with
  `pyproject.toml`, no hardcoding.
- **Trennlinie:** 40× `─` (U+2500 BOX DRAWINGS LIGHT HORIZONTAL) — consistent width,
  unicode box-drawing character for a clean look.
- **Leerzeile nach Banner** — separates decoration from structured log output visually.
- **Placement:** Called in `_run_gateway` after `settings = Settings.load(...)` but before
  `_setup_logging` has been called... wait — `_setup_logging` is called in the `gateway`
  command function before `asyncio.run(_run_gateway(...))`. So logging is already configured
  when `_run_gateway` runs. The banner prints to stderr via `print`, so it appears before
  the first `logger.info` line regardless.

## No Tests Needed

The banner is a side-effecting print to stderr. No logic to unit-test. Existing 104 tests
must continue to pass.

## Files Changed

| File | Change |
|---|---|
| `squidbot/cli/main.py` | Add `_print_banner()`, call it at top of `_run_gateway` |
