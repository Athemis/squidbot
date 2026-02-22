# Loguru Brace-Style Migration Design

**Date:** 2026-02-22
**Status:** Approved

## Overview

Migrate all loguru `logger.*` calls that use f-strings to the idiomatic brace-style
(`{}`) lazy argument passing. Literal string calls (no interpolation) are left unchanged.

## Motivation

loguru's `logger.*` functions are equivalent to `str.format()` — they accept positional
and keyword arguments and only format the string if the log level is active (lazy
evaluation). f-strings are eager: the string is always built, even if the level is
suppressed. Brace-style is therefore both more efficient and more idiomatic for loguru.

`%s`/`%d` placeholder style is **not** supported by loguru and must never be used.

## Scope

Two files contain logger calls with f-string interpolation:

### `squidbot/core/heartbeat.py`

| Line | Current | After |
|---|---|---|
| 164 | `logger.warning(f"...{tz_name!r}...")` | `logger.warning("...{!r}...", tz_name)` |
| 246 | `logger.error(f"heartbeat: agent error: {e}")` | `logger.error("heartbeat: agent error: {}", e)` |
| 264 | `logger.error(f"heartbeat: delivery error: {e}")` | `logger.error("heartbeat: delivery error: {}", e)` |
| 278 | `logger.info(f"heartbeat: started (every {self._config.interval_minutes}m)")` | `logger.info("heartbeat: started (every {}m)", self._config.interval_minutes)` |
| 285 | `logger.error(f"heartbeat: unexpected error in tick: {e}")` | `logger.error("heartbeat: unexpected error in tick: {}", e)` |

### `squidbot/cli/main.py`

| Line | Current | After |
|---|---|---|
| 329 | `logger.info(f"matrix: {matrix_state}")` | `logger.info("matrix: {}", matrix_state)` |
| 330 | `logger.info(f"email: {email_state}")` | `logger.info("email: {}", email_state)` |
| 334–337 | multiline f-string | multiline brace-style (see below) |
| 343 | `logger.info(f"cron: {len(cron_jobs)} jobs loaded")` | `logger.info("cron: {} jobs loaded", len(cron_jobs))` |

Multiline (lines 334–337), after:
```python
logger.info(
    "heartbeat: every {}m, active {}-{} {}",
    hb.interval_minutes, hb.active_hours_start, hb.active_hours_end, hb.timezone
)
```

## Out of Scope

- Literal-string calls with no interpolation — unchanged
- Test files — no logger calls there
- Any future files — covered by AGENTS.md guidelines

## Testing

No new tests needed. The change is purely cosmetic at runtime (identical output).
Existing 104 tests must continue to pass. Ruff must be clean.

## Files Changed

| File | Change |
|---|---|
| `squidbot/core/heartbeat.py` | 5 f-strings → brace-style |
| `squidbot/cli/main.py` | 4 f-strings → brace-style |
