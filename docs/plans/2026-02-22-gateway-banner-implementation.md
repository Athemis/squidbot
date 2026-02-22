# Gateway Startup Banner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a 🦑 emoji banner with version, model and workspace info to `squidbot gateway` startup.

**Architecture:** A single `_print_banner(settings)` helper in `cli/main.py` prints to `sys.stderr` directly (no loguru) and is called at the top of `_run_gateway`, before any `logger.info` calls. No new dependencies.

**Tech Stack:** Python stdlib `importlib.metadata`, `sys.stderr`, f-strings.

---

### Task 1: Add `_print_banner()` and call it in `_run_gateway`

**Files:**
- Modify: `squidbot/cli/main.py`

No tests needed — side-effecting stderr print, no logic. Existing 104 tests must still pass.

**Step 1: Add `_print_banner` helper**

Place it in the `# ── Internal helpers` section, immediately before `_setup_logging` (around line 184). The full function:

```python
def _print_banner(settings: Settings) -> None:
    """
    Print the gateway startup banner to stderr.

    Uses plain print() rather than loguru so the banner is not prefixed
    with a timestamp and log level.

    Args:
        settings: Loaded application settings.
    """
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

**Step 2: Call `_print_banner` at the top of `_run_gateway`**

In `_run_gateway`, after `settings = Settings.load(config_path)` and before the `# Startup summary` block, add:

```python
    settings = Settings.load(config_path)
    _print_banner(settings)

    # Startup summary
    logger.info("gateway starting")
    ...
```

The full beginning of `_run_gateway` should look like:

```python
async def _run_gateway(config_path: Path) -> None:
    """Start all enabled channels concurrently.

    The gateway does not start a CLI channel — use `squidbot agent` for
    interactive terminal use. Log output goes to stderr; control the bot
    via Matrix or Email.
    """
    from loguru import logger  # noqa: PLC0415

    from squidbot.adapters.persistence.jsonl import JsonlMemory  # noqa: PLC0415
    from squidbot.core.heartbeat import HeartbeatService, LastChannelTracker  # noqa: PLC0415
    from squidbot.core.models import Session  # noqa: PLC0415
    from squidbot.core.scheduler import CronScheduler  # noqa: PLC0415

    settings = Settings.load(config_path)
    _print_banner(settings)

    # Startup summary
    logger.info("gateway starting")
    ...
```

**Step 3: Run ruff and tests**

```bash
uv run ruff check .
uv run pytest -q
```

Expected: ruff clean, 104 tests pass.

**Step 4: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "feat: add emoji banner to gateway startup"
```

**Step 5: Smoke test**

```bash
uv tool install --reinstall /home/alex/git/squidbot
timeout 3 squidbot gateway 2>&1 || true
```

Expected output:

```
🦑 squidbot v0.1.0
   model:     anthropic/claude-opus-4-5
   workspace: /home/alex/squidbot-workspace
   ────────────────────────────────────────

2026-02-22 12:25:03 INFO     gateway starting
2026-02-22 12:25:03 INFO     matrix: disabled
2026-02-22 12:25:03 INFO     email: disabled
2026-02-22 12:25:03 INFO     heartbeat: every 30m, active 00:00-24:00 local
2026-02-22 12:25:03 INFO     cron: 0 jobs loaded
2026-02-22 12:25:04 INFO     heartbeat: started (every 30m)
```
