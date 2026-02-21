"""
Cron scheduler for recurring and one-time tasks.

Parses cron expressions ("0 9 * * *") and interval expressions ("every 3600").
The scheduler runs as a background asyncio task and triggers the agent loop
for each due job.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any

from cronsim import CronSim

from squidbot.core.models import CronJob
from squidbot.core.ports import MemoryPort

# Poll interval: check for due jobs every minute
POLL_INTERVAL_SECONDS = 60


def parse_schedule(job: CronJob, now: datetime | None = None) -> datetime | None:
    """
    Compute the next run time for a job.

    Supports:
    - Cron expressions: "0 9 * * *"
    - Interval expressions: "every N" (seconds)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    schedule = job.schedule.strip()
    if schedule.startswith("every "):
        try:
            int(schedule.split()[1])
            return now.replace(microsecond=0)
        except IndexError, ValueError:
            return None

    try:
        cron = CronSim(schedule, now)
        return next(iter(cron))
    except Exception:
        return None


def is_due(job: CronJob, now: datetime | None = None) -> bool:
    """
    Return True if the job should run now.

    A job is due if its next scheduled time is <= now and it hasn't
    run in the current scheduling window.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if not job.enabled:
        return False

    schedule = job.schedule.strip()

    if schedule.startswith("every "):
        try:
            seconds = int(schedule.split()[1])
            if job.last_run is None:
                return True
            elapsed = (now - job.last_run).total_seconds()
            return elapsed >= seconds
        except IndexError, ValueError:
            return False

    # Cron expression: check if we're past the next scheduled time.
    # When last_run is None, use (now - 1 minute) as baseline so we find
    # the next occurrence from just before now. This avoids firing jobs that
    # haven't been scheduled yet (their next fire time is in the future).
    from datetime import timedelta

    baseline = job.last_run if job.last_run is not None else (now - timedelta(minutes=1))
    try:
        cron = CronSim(schedule, baseline)
        next_run = next(iter(cron))
        return next_run <= now
    except Exception:
        return False


class CronScheduler:
    """
    Background scheduler that polls for due jobs and triggers the agent.

    The scheduler loads jobs from storage, checks which are due, runs them
    via the provided callback, and updates last_run.
    """

    def __init__(self, storage: MemoryPort) -> None:
        self._storage = storage
        self._running = False

    async def run(self, on_due: Callable[[CronJob], Coroutine[Any, Any, None]]) -> None:
        """
        Start the scheduler loop.

        Args:
            on_due: Async callback invoked with (job: CronJob) for each due job.
        """
        self._running = True
        while self._running:
            await self._tick(on_due)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _tick(self, on_due: Callable[[CronJob], Coroutine[Any, Any, None]]) -> None:
        jobs = await self._storage.load_cron_jobs()
        now = datetime.now(timezone.utc)
        updated = False
        for job in jobs:
            if is_due(job, now=now):
                job.last_run = now
                updated = True
                try:
                    await on_due(job)
                except Exception:
                    pass  # Don't crash the scheduler on handler errors
        if updated:
            await self._storage.save_cron_jobs(jobs)

    def stop(self) -> None:
        self._running = False
