# Gateway Logging Design

**Date:** 2026-02-22
**Status:** Approved

## Overview

Add structured logging to the squidbot gateway using **loguru**. The gateway currently
produces no log output (stdlib `logging` calls in `heartbeat.py` have no handler configured,
and `cli/main.py` uses ad-hoc `print()` calls). This design replaces both with a consistent,
configurable logging setup.

## Goals

- Structured log output to stderr with timestamp + level
- Configurable log level via `--log-level` CLI flag (default: INFO)
- Startup summary showing which channels/services are active
- Third-party libraries (httpx, nio, etc.) silenced to WARNING
- No test regressions — loguru produces no output in tests by default

## Library: loguru

loguru is chosen over stdlib `logging` for:
- Zero per-module boilerplate: `from loguru import logger` — done
- Robust configuration: `logger.remove()` + `logger.add()`, no `basicConfig()` race conditions
- Built-in color support, clean format string

New dependency: `loguru>=0.7`

## Configuration

`_setup_logging(level: str)` is called once at the start of `gateway` and `agent` commands
in `cli/main.py`:

```python
def _setup_logging(level: str) -> None:
    import sys
    import logging
    from loguru import logger

    logger.remove()  # remove loguru's default stderr handler
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
    # Silence noisy third-party libraries
    for noisy in ("httpx", "nio", "aioimaplib", "aiosmtplib", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
```

## CLI Flag

Added to both `gateway` and `agent` commands:

```python
@app.command
def gateway(
    config: Path = DEFAULT_CONFIG_PATH,
    log_level: str = "INFO",
) -> None:
    ...
```

Usage:
```bash
squidbot gateway                    # INFO level
squidbot gateway --log-level DEBUG  # DEBUG level (shows heartbeat skips, etc.)
squidbot agent --log-level WARNING  # suppress most output
```

## Startup Log (gateway only)

Emitted at INFO level immediately after loading settings:

```
2026-02-22 14:30:00 INFO     gateway starting
2026-02-22 14:30:00 INFO     matrix: disabled
2026-02-22 14:30:00 INFO     email: disabled
2026-02-22 14:30:00 INFO     heartbeat: every 30m, active 08:00-22:00 Europe/Berlin
2026-02-22 14:30:00 INFO     cron: 2 jobs loaded
```

## Migration: heartbeat.py

Replace stdlib logging with loguru:

```python
# Before
import logging
logger = logging.getLogger(__name__)

# After
from loguru import logger
```

All existing `logger.debug/info/warning/error` call sites remain unchanged — loguru's
API is a drop-in replacement.

## Format

```
2026-02-22 14:30:00 INFO     heartbeat: started (every 30m)
2026-02-22 14:30:00 DEBUG    heartbeat: skipped (outside active hours)
2026-02-22 14:31:00 WARNING  heartbeat: unknown timezone 'Foo/Bar', falling back to local
2026-02-22 14:32:00 ERROR    heartbeat: agent error: ConnectionError
```

Level is left-padded to 8 chars for alignment. Color is applied by level
(green=DEBUG, blue=INFO, yellow=WARNING, red=ERROR).

## Testing

No new tests needed. loguru by default has no sink in test environments — all
`logger.*` calls are no-ops unless a sink is added. Existing tests are unaffected.

## Files Changed

| File | Change |
|---|---|
| `pyproject.toml` | Add `loguru>=0.7` dependency |
| `squidbot/cli/main.py` | Add `_setup_logging()`, call it in `gateway` and `agent`, add `--log-level` flag, add gateway startup log |
| `squidbot/core/heartbeat.py` | Replace `import logging` / `logging.getLogger(__name__)` with `from loguru import logger` |
