# Gateway Logging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add structured loguru logging to the squidbot gateway with configurable log level, startup summary, and migration of heartbeat.py from stdlib logging.

**Architecture:** `_setup_logging(level)` is called once per CLI command in `cli/main.py`. loguru replaces stdlib `logging` in `heartbeat.py` — same API, no test changes needed. All third-party library loggers are silenced to WARNING via the stdlib bridge.

**Tech Stack:** loguru>=0.7, cyclopts (existing), Python 3.14

---

### Task 1: Add loguru dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add loguru to dependencies**

In `pyproject.toml`, add `"loguru>=0.7",` to the `dependencies` list (after `rich>=13.0`):

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
    "duckduckgo-search>=8.0",
    "rich>=13.0",
    "loguru>=0.7",
]
```

**Step 2: Install the new dependency**

```bash
uv sync
```

Expected: loguru is downloaded and installed.

**Step 3: Verify import works**

```bash
uv run python -c "from loguru import logger; print('ok')"
```

Expected: `ok`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add loguru>=0.7"
```

---

### Task 2: Implement `_setup_logging()` in cli/main.py

**Files:**
- Modify: `squidbot/cli/main.py`

No new tests needed — loguru has no sink in test environments, so all existing tests remain unaffected. We verify manually.

**Step 1: Add `_setup_logging` helper**

At the top of the `# ── Internal helpers ─────────────────────────────────────────────────────────` section (just before `_make_agent_loop`), add:

```python
def _setup_logging(level: str) -> None:
    """
    Configure loguru for gateway/agent output.

    Removes the default loguru stderr handler and replaces it with one that
    uses a consistent timestamp+level format. Third-party libraries that are
    too chatty at DEBUG are clamped to WARNING via the stdlib logging bridge.

    Args:
        level: Log level string (case-insensitive), e.g. "INFO", "DEBUG".
    """
    import logging
    import sys

    from loguru import logger

    logger.remove()  # remove loguru's built-in default handler
    logger.add(
        sys.stderr,
        level=level.upper(),
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
            "<level>{level:<8}</level> "
            "{message}"
        ),
        colorize=True,
    )
    for noisy in ("httpx", "nio", "aioimaplib", "aiosmtplib", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
```

**Step 2: Add `--log-level` flag to `gateway` command and call `_setup_logging`**

Replace:
```python
@app.command
def gateway(config: Path = DEFAULT_CONFIG_PATH) -> None:
    """Start the gateway (all enabled channels run concurrently)."""
    asyncio.run(_run_gateway(config_path=config))
```

With:
```python
@app.command
def gateway(config: Path = DEFAULT_CONFIG_PATH, log_level: str = "INFO") -> None:
    """Start the gateway (all enabled channels run concurrently)."""
    _setup_logging(log_level)
    asyncio.run(_run_gateway(config_path=config))
```

**Step 3: Add `--log-level` flag to `agent` command and call `_setup_logging`**

Replace:
```python
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
```

With:
```python
@app.command
def agent(
    message: str | None = None,
    config: Path = DEFAULT_CONFIG_PATH,
    log_level: str = "INFO",
) -> None:
    """
    Chat with the assistant.

    In interactive mode (no --message), starts a REPL loop.
    With --message, sends a single message and exits.
    """
    _setup_logging(log_level)
    asyncio.run(_run_agent(message=message, config_path=config))
```

**Step 4: Run ruff and tests**

```bash
uv run ruff check .
uv run pytest -q
```

Expected: ruff clean, all tests pass.

**Step 5: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "feat: add _setup_logging() with loguru and --log-level flag"
```

---

### Task 3: Add gateway startup summary log

**Files:**
- Modify: `squidbot/cli/main.py` (the `_run_gateway` async helper)

**Step 1: Add loguru import and startup log block to `_run_gateway`**

At the top of `_run_gateway`, after `settings = Settings.load(config_path)` is called, add the startup summary. The final function should look like this (showing only the changed beginning):

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

    # Startup summary
    logger.info("gateway starting")
    matrix_state = "enabled" if settings.channels.matrix.enabled else "disabled"
    email_state = "enabled" if settings.channels.email.enabled else "disabled"
    logger.info(f"matrix: {matrix_state}")
    logger.info(f"email: {email_state}")

    hb = settings.agents.heartbeat
    if hb.enabled:
        logger.info(
            f"heartbeat: every {hb.interval_minutes}m, "
            f"active {hb.active_hours_start}-{hb.active_hours_end} {hb.timezone}"
        )
    else:
        logger.info("heartbeat: disabled")

    storage = JsonlMemory(base_dir=Path.home() / ".squidbot")
    cron_jobs = await storage.load_cron_jobs()
    logger.info(f"cron: {len(cron_jobs)} jobs loaded")

    agent_loop = await _make_agent_loop(settings)
    workspace = Path(settings.agents.workspace).expanduser()
    # ... rest of function unchanged ...
```

Note: `storage` is created earlier than before (before `agent_loop`) so we can log cron count. The `storage` variable is then reused for `CronScheduler`. The full updated function:

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

    # Startup summary
    logger.info("gateway starting")
    matrix_state = "enabled" if settings.channels.matrix.enabled else "disabled"
    email_state = "enabled" if settings.channels.email.enabled else "disabled"
    logger.info(f"matrix: {matrix_state}")
    logger.info(f"email: {email_state}")

    hb = settings.agents.heartbeat
    if hb.enabled:
        logger.info(
            f"heartbeat: every {hb.interval_minutes}m, "
            f"active {hb.active_hours_start}-{hb.active_hours_end} {hb.timezone}"
        )
    else:
        logger.info("heartbeat: disabled")

    storage = JsonlMemory(base_dir=Path.home() / ".squidbot")
    cron_jobs = await storage.load_cron_jobs()
    logger.info(f"cron: {len(cron_jobs)} jobs loaded")

    agent_loop = await _make_agent_loop(settings)
    workspace = Path(settings.agents.workspace).expanduser()

    tracker = LastChannelTracker()

    # Map of channel prefix → channel instance for cron job routing
    channel_registry: dict[str, object] = {}

    async def on_cron_due(job) -> None:
        """Deliver a scheduled message to the job's target channel."""
        channel_prefix = job.channel.split(":")[0]
        ch = channel_registry.get(channel_prefix)
        if ch is None:
            return  # target channel not active
        session = Session(
            channel=channel_prefix,
            sender_id=job.channel.split(":", 1)[1],
        )
        await agent_loop.run(session, job.message, ch)  # type: ignore[arg-type]

    scheduler = CronScheduler(storage=storage)
    heartbeat = HeartbeatService(
        agent_loop=agent_loop,
        tracker=tracker,
        workspace=workspace,
        config=settings.agents.heartbeat,
    )

    async with asyncio.TaskGroup() as tg:
        tg.create_task(scheduler.run(on_due=on_cron_due))
        tg.create_task(heartbeat.run())
```

**Step 2: Run ruff and tests**

```bash
uv run ruff check .
uv run pytest -q
```

Expected: ruff clean, all tests pass.

**Step 3: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "feat: add gateway startup summary log"
```

---

### Task 4: Migrate heartbeat.py from stdlib logging to loguru

**Files:**
- Modify: `squidbot/core/heartbeat.py`

The existing `logger.debug/info/warning/error` call sites are unchanged — loguru is a drop-in replacement. Only the import changes.

**Step 1: Replace the stdlib import**

In `squidbot/core/heartbeat.py`, replace:

```python
import logging
```

with nothing (remove the line), and replace:

```python
logger = logging.getLogger(__name__)
```

with:

```python
from loguru import logger
```

The imports block should look like this afterward:

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from squidbot.config.schema import HeartbeatConfig
from squidbot.core.agent import AgentLoop
from squidbot.core.models import Session
from squidbot.core.ports import ChannelPort
```

**Step 2: Run ruff and tests**

```bash
uv run ruff check .
uv run pytest -q
```

Expected: ruff clean, all 104+ tests pass.

**Step 3: Commit**

```bash
git add squidbot/core/heartbeat.py
git commit -m "refactor: migrate heartbeat.py from stdlib logging to loguru"
```

---

### Task 5: Manual smoke test

**Step 1: Reinstall the CLI tool**

```bash
uv tool install --reinstall /home/alex/git/squidbot
```

**Step 2: Test --help shows new flags**

```bash
squidbot gateway --help
squidbot agent --help
```

Expected: Both commands show a `--log-level` option.

**Step 3: Test startup log output**

```bash
squidbot gateway 2>&1 | head -10
```

Expected output (approximate):

```
2026-02-22 14:30:00 INFO     gateway starting
2026-02-22 14:30:00 INFO     matrix: disabled
2026-02-22 14:30:00 INFO     email: disabled
2026-02-22 14:30:00 INFO     heartbeat: disabled
2026-02-22 14:30:00 INFO     cron: 0 jobs loaded
```

**Step 4: Test DEBUG level shows more output**

```bash
squidbot gateway --log-level DEBUG 2>&1 | head -20
```

Expected: Same startup lines, plus additional DEBUG lines from heartbeat internals once it ticks.

**Step 5: Test WARNING level suppresses INFO**

```bash
squidbot gateway --log-level WARNING 2>&1 | head -5
```

Expected: No output (startup INFO lines are suppressed).
