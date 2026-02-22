# Loguru Brace-Style Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace all f-string interpolation in `logger.*` calls with loguru's idiomatic `{}` brace-style lazy argument passing.

**Architecture:** Pure mechanical substitution — no logic changes, no new tests. Two files affected. Literal-string calls (no interpolation) are left untouched.

**Tech Stack:** loguru>=0.7 (already installed), Python 3.14

---

### Task 1: Migrate `squidbot/core/heartbeat.py`

**Files:**
- Modify: `squidbot/core/heartbeat.py`

No tests needed — the output is identical; only the formatting mechanism changes.

**Step 1: Apply the 5 substitutions**

Open `squidbot/core/heartbeat.py` and make these exact replacements:

**Line 164** — f-string with `!r`:
```python
# Before
logger.warning(f"heartbeat: unknown timezone {tz_name!r}, falling back to local")

# After
logger.warning("heartbeat: unknown timezone {!r}, falling back to local", tz_name)
```

**Line 246** — agent error:
```python
# Before
logger.error(f"heartbeat: agent error: {e}")

# After
logger.error("heartbeat: agent error: {}", e)
```

**Line 264** — delivery error:
```python
# Before
logger.error(f"heartbeat: delivery error: {e}")

# After
logger.error("heartbeat: delivery error: {}", e)
```

**Line 278** — started message:
```python
# Before
logger.info(f"heartbeat: started (every {self._config.interval_minutes}m)")

# After
logger.info("heartbeat: started (every {}m)", self._config.interval_minutes)
```

**Line 285** — unexpected error:
```python
# Before
logger.error(f"heartbeat: unexpected error in tick: {e}")

# After
logger.error("heartbeat: unexpected error in tick: {}", e)
```

**Step 2: Verify no f-strings remain in logger calls**

```bash
grep -n "logger\..*f\"" squidbot/core/heartbeat.py
```

Expected: no output.

**Step 3: Run ruff and tests**

```bash
uv run ruff check .
uv run pytest -q
```

Expected: ruff clean, 104 tests pass.

**Step 4: Commit**

```bash
git add squidbot/core/heartbeat.py
git commit -m "refactor: use brace-style args in heartbeat.py logger calls"
```

---

### Task 2: Migrate `squidbot/cli/main.py`

**Files:**
- Modify: `squidbot/cli/main.py`

**Step 1: Apply the 4 substitutions**

Open `squidbot/cli/main.py` and find the `_run_gateway` async function. Make these exact replacements:

**matrix state log:**
```python
# Before
logger.info(f"matrix: {matrix_state}")

# After
logger.info("matrix: {}", matrix_state)
```

**email state log:**
```python
# Before
logger.info(f"email: {email_state}")

# After
logger.info("email: {}", email_state)
```

**heartbeat multiline log** (currently an f-string over two lines):
```python
# Before
logger.info(
    f"heartbeat: every {hb.interval_minutes}m, "
    f"active {hb.active_hours_start}-{hb.active_hours_end} {hb.timezone}"
)

# After
logger.info(
    "heartbeat: every {}m, active {}-{} {}",
    hb.interval_minutes, hb.active_hours_start, hb.active_hours_end, hb.timezone
)
```

**cron count log:**
```python
# Before
logger.info(f"cron: {len(cron_jobs)} jobs loaded")

# After
logger.info("cron: {} jobs loaded", len(cron_jobs))
```

**Step 2: Verify no f-strings remain in logger calls**

```bash
grep -n "logger\..*f\"" squidbot/cli/main.py
```

Expected: no output.

**Step 3: Run ruff and tests**

```bash
uv run ruff check .
uv run pytest -q
```

Expected: ruff clean, 104 tests pass.

**Step 4: Commit**

```bash
git add squidbot/cli/main.py
git commit -m "refactor: use brace-style args in main.py logger calls"
```

---

### Task 3: Smoke test

**Step 1: Reinstall CLI**

```bash
uv tool install --reinstall /home/alex/git/squidbot
```

**Step 2: Verify gateway startup output is unchanged**

```bash
timeout 3 squidbot gateway 2>&1 || true
```

Expected (same content as before migration, timestamps will differ):
```
2026-02-22 12:14:33 INFO     gateway starting
2026-02-22 12:14:33 INFO     matrix: disabled
2026-02-22 12:14:33 INFO     email: disabled
2026-02-22 12:14:33 INFO     heartbeat: every 30m, active 00:00-24:00 local
2026-02-22 12:14:33 INFO     cron: 0 jobs loaded
2026-02-22 12:14:34 INFO     heartbeat: started (every 30m)
```
