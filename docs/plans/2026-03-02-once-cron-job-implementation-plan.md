# Once-Cron-Job Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Einmalig ausführbare Cron-Jobs durch `once: bool = False` auf `CronJob` ermöglichen — nach dem Auslösen wird der Job automatisch gelöscht.

**Architecture:** Minimale Modellerweiterung (`once` Flag), Logik-Änderung in `_tick()` (Löschen statt `last_run` setzen), Validierung in `cron_ops.validate_job()`, Tool-Erweiterung in `CronAddTool`.

**Tech Stack:** Python 3.14, cronsim (unverändert), pytest, mypy --strict

---

## Task 1: `CronJob` Modell erweitern

**Files:**
- Modify: `squidbot/core/models.py:138` (nach `last_run`)
- Test: `tests/core/test_cron_ops.py`

**Step 1: Failing tests schreiben** (am Ende von `tests/core/test_cron_ops.py`):

```python
def test_cronjob_once_flag_defaults_to_false() -> None:
    job = _job()
    assert job.once is False


def test_cronjob_once_flag_can_be_set() -> None:
    job = _job(once=True)
    assert job.once is True
```

**Step 2: Test ausführen und Fehler bestätigen:**
```bash
uv run pytest tests/core/test_cron_ops.py::test_cronjob_once_flag_defaults_to_false -v
```
Erwartet: `FAILED` — `TypeError: CronJob.__init__() got an unexpected keyword argument 'once'`

**Step 3: Implementierung** — in `squidbot/core/models.py` nach `last_run: datetime | None = None`:
```python
once: bool = False
```

**Step 4: Tests ausführen:**
```bash
uv run pytest tests/core/test_cron_ops.py -v
```
Erwartet: alle PASS

**Step 5: Mypy:**
```bash
uv run mypy squidbot/core/models.py
```

**Step 6: Commit:**
```bash
git add squidbot/core/models.py tests/core/test_cron_ops.py
git commit -m "feat: add once field to CronJob model"
```

---

## Task 2: Validierung in `cron_ops.validate_job()`

**Files:**
- Modify: `squidbot/core/cron_ops.py:22-35`
- Test: `tests/core/test_cron_ops.py`

**Step 1: Failing tests schreiben** (am Ende von `tests/core/test_cron_ops.py`):

```python
def test_validate_job_rejects_once_with_interval_schedule() -> None:
    now = datetime(2026, 3, 2, 10, 0, tzinfo=UTC)
    error = validate_job(_job(schedule="every 3600", once=True), now=now)
    assert error is not None
    assert "once" in error.lower()


def test_validate_job_accepts_once_with_cron_expression() -> None:
    now = datetime(2026, 3, 2, 10, 0, tzinfo=UTC)
    assert validate_job(_job(schedule="30 15 3 3 *", once=True), now=now) is None
```

**Step 2: Test ausführen:**
```bash
uv run pytest tests/core/test_cron_ops.py::test_validate_job_rejects_once_with_interval_schedule -v
```
Erwartet: `FAILED` — Validation gibt kein Fehler zurück für `once + every N`

**Step 3: Implementierung** — am Anfang von `validate_job()`, vor dem `parse_schedule`-Aufruf:
```python
if job.once and job.schedule.strip().startswith("every "):
    return "once=True is not compatible with interval schedules ('every N'). Use a cron expression."
```

**Step 4: Tests ausführen:**
```bash
uv run pytest tests/core/test_cron_ops.py -v
```

**Step 5: Commit:**
```bash
git add squidbot/core/cron_ops.py tests/core/test_cron_ops.py
git commit -m "feat: reject once=True with interval schedules in validate_job"
```

---

## Task 3: `format_jobs()` — `[once]` Anzeige

**Files:**
- Modify: `squidbot/core/cron_ops.py:89-102`
- Test: `tests/core/test_cron_ops.py`

**Step 1: Failing tests** (am Ende von `tests/core/test_cron_ops.py`):

```python
def test_format_jobs_shows_once_label_for_once_jobs() -> None:
    job = _job(once=True)
    output = format_jobs([job])
    assert "[once]" in output


def test_format_jobs_does_not_show_once_label_for_recurring_jobs() -> None:
    job = _job(once=False)
    output = format_jobs([job])
    assert "[once]" not in output
```

**Step 2: Test ausführen:**
```bash
uv run pytest tests/core/test_cron_ops.py::test_format_jobs_shows_once_label_for_once_jobs -v
```
Erwartet: `FAILED`

**Step 3: Implementierung** — in `format_jobs()`, die erste `lines.append`-Zeile anpassen:
```python
once_label = "  [once]" if job.once else ""
lines.append(f"  [{state}] {job.id}  {job.name}{once_label}")
```

**Step 4: Tests ausführen:**
```bash
uv run pytest tests/core/test_cron_ops.py -v
```

**Step 5: Commit:**
```bash
git add squidbot/core/cron_ops.py tests/core/test_cron_ops.py
git commit -m "feat: show [once] label in format_jobs for one-time cron jobs"
```

---

## Task 4: `set_enabled()` — `once` propagieren

**Files:**
- Modify: `squidbot/core/cron_ops.py:64-86`
- Test: `tests/core/test_cron_ops.py`

**Step 1: Failing test** (am Ende von `tests/core/test_cron_ops.py`):

```python
def test_set_enabled_preserves_once_flag() -> None:
    job = _job(once=True)
    updated, found = set_enabled([job], job.id, False)
    assert found
    assert updated[0].once is True
```

**Step 2: Test ausführen:**
```bash
uv run pytest tests/core/test_cron_ops.py::test_set_enabled_preserves_once_flag -v
```
Erwartet: `FAILED` — `once` geht bei der Rekonstruktion verloren

**Step 3: Implementierung** — `CronJob(...)`-Konstruktoraufruf in `set_enabled()` um `once=job.once` ergänzen.

**Step 4: Tests ausführen + Commit:**
```bash
uv run pytest tests/core/test_cron_ops.py -v
git add squidbot/core/cron_ops.py tests/core/test_cron_ops.py
git commit -m "fix: preserve once flag in set_enabled"
```

---

## Task 5: `CronScheduler._tick()` — Job nach Auslösung löschen

**Files:**
- Modify: `squidbot/core/scheduler.py:159-172`
- Test: `tests/core/test_scheduler.py`

**Step 1: Failing tests** (am Ende von `tests/core/test_scheduler.py` anfügen):

```python
async def test_tick_deletes_once_job_after_firing() -> None:
    from datetime import UTC, datetime

    from squidbot.core.models import CronJob
    from squidbot.core.scheduler import CronScheduler

    fired: list[CronJob] = []

    class FakeStorage:
        def __init__(self) -> None:
            self.saved: list[CronJob] = []
            self.jobs = [
                CronJob(
                    id="aaa00001",
                    name="one-time",
                    message="ping",
                    schedule="* * * * *",  # always due
                    channel="cli:local",
                    once=True,
                )
            ]

        async def load_cron_jobs(self) -> list[CronJob]:
            return list(self.jobs)

        async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
            self.saved = list(jobs)

    storage = FakeStorage()
    scheduler = CronScheduler(storage=storage)

    async def capture(job: CronJob) -> None:
        fired.append(job)

    await scheduler._tick(capture)

    assert len(fired) == 1
    assert storage.saved == []  # job was deleted


async def test_tick_keeps_recurring_job_after_firing() -> None:
    from squidbot.core.models import CronJob
    from squidbot.core.scheduler import CronScheduler

    class FakeStorage:
        def __init__(self) -> None:
            self.saved: list[CronJob] = []
            self.jobs = [
                CronJob(
                    id="bbb00002",
                    name="recurring",
                    message="ping",
                    schedule="* * * * *",
                    channel="cli:local",
                    once=False,
                )
            ]

        async def load_cron_jobs(self) -> list[CronJob]:
            return list(self.jobs)

        async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
            self.saved = list(jobs)

    storage = FakeStorage()
    scheduler = CronScheduler(storage=storage)

    async def noop(job: CronJob) -> None:
        pass

    await scheduler._tick(noop)

    assert len(storage.saved) == 1
    assert storage.saved[0].id == "bbb00002"
    assert storage.saved[0].last_run is not None
```

**Step 2: Tests ausführen:**
```bash
uv run pytest tests/core/test_scheduler.py::test_tick_deletes_once_job_after_firing -v
```
Erwartet: `FAILED`

**Step 3: Implementierung** — `_tick()` in `squidbot/core/scheduler.py` ersetzen:

```python
async def _tick(self, on_due: Callable[[CronJob], Coroutine[Any, Any, None]]) -> None:
    jobs = await self._storage.load_cron_jobs()
    now = datetime.now(UTC)
    kept: list[CronJob] = []
    changed = False
    for job in jobs:
        if not is_due(job, now=now):
            kept.append(job)
            continue
        changed = True
        try:  # noqa: SIM105 — contextlib.suppress doesn't support async
            await on_due(job)
        except Exception:
            pass
        if not job.once:
            job.last_run = now
            kept.append(job)
        # once=True: intentionally not appended → deleted after firing
    if changed:
        await self._storage.save_cron_jobs(kept)
```

**Step 4: Tests ausführen:**
```bash
uv run pytest tests/core/test_scheduler.py -v
```

**Step 5: Mypy + Commit:**
```bash
uv run mypy squidbot/core/scheduler.py
git add squidbot/core/scheduler.py tests/core/test_scheduler.py
git commit -m "feat: delete once-jobs after firing in CronScheduler._tick"
```

---

## Task 6: `CronAddTool` — `once` Parameter hinzufügen

**Files:**
- Modify: `squidbot/adapters/tools/cron.py:27-129`
- Test: `tests/adapters/tools/test_cron_tools.py`

**Step 1: Failing tests** (neue Funktionen in `tests/adapters/tools/test_cron_tools.py`):

```python
async def test_cron_add_tool_creates_once_job() -> None:
    from squidbot.adapters.tools.cron import CronAddTool
    from squidbot.core.models import CronJob

    jobs_store: list[CronJob] = []

    class FakeStorage:
        async def load_cron_jobs(self) -> list[CronJob]:
            return list(jobs_store)

        async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
            jobs_store.clear()
            jobs_store.extend(jobs)

    tool = CronAddTool(
        storage=FakeStorage(),  # type: ignore[arg-type]
        default_channel="matrix:@user:example.com",
        default_metadata={"matrix_room_id": "!abc:example.com"},
    )
    result = await tool.execute(
        name="Zahnarzt",
        message="Nicht vergessen!",
        schedule="30 15 3 3 *",
        once=True,
    )
    assert not result.is_error, result.content
    assert len(jobs_store) == 1
    assert jobs_store[0].once is True


async def test_cron_add_tool_rejects_once_with_interval() -> None:
    from squidbot.adapters.tools.cron import CronAddTool
    from squidbot.core.models import CronJob

    class FakeStorage:
        async def load_cron_jobs(self) -> list[CronJob]:
            return []

        async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
            pass

    tool = CronAddTool(
        storage=FakeStorage(),  # type: ignore[arg-type]
        default_channel="matrix:@user:example.com",
        default_metadata={"matrix_room_id": "!abc:example.com"},
    )
    result = await tool.execute(
        name="Test",
        message="msg",
        schedule="every 3600",
        once=True,
    )
    assert result.is_error
    assert "once" in result.content.lower()
```

**Step 2: Tests ausführen:**
```bash
uv run pytest tests/adapters/tools/test_cron_tools.py::test_cron_add_tool_creates_once_job -v
```
Erwartet: `FAILED`

**Step 3: Implementierung** in `CronAddTool`:

Schema: unter `"enabled"` einfügen:
```python
"once": {
    "type": "boolean",
    "description": (
        "If true, the job runs exactly once and is deleted after firing. "
        "Requires a cron expression (e.g. '30 15 3 3 *'), not an interval."
    ),
},
```

In `execute()` nach `enabled_raw`-Block:
```python
once_raw = kwargs.get("once", False)
if not isinstance(once_raw, bool):
    return ToolResult(tool_call_id="", content="Error: once must be a boolean", is_error=True)
```

`CronJob(...)`-Konstruktor: `once=once_raw` hinzufügen.

**Step 4: Tests ausführen:**
```bash
uv run pytest tests/adapters/tools/test_cron_tools.py -v
```

**Step 5: Vollständiger Check + Commit:**
```bash
uv run pytest
uv run mypy squidbot/
uv run ruff check .
git add squidbot/adapters/tools/cron.py tests/adapters/tools/test_cron_tools.py
git commit -m "feat: add once parameter to CronAddTool"
```

---

## Task 7: Abschluss-Check

```bash
uv run pytest
uv run mypy squidbot/
uv run ruff check .
uv run ruff format . --check
```

Alle Tests grün, keine mypy-Fehler, kein ruff-Fehler → fertig. Dann PR öffnen.
