"""Pure cron job operations shared by CLI and tools.

This module contains only deterministic business logic for creating, validating,
mutating, and formatting cron jobs. It deliberately performs no I/O so both CLI
commands and agent tools can reuse one implementation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from squidbot.core.models import CronJob
from squidbot.core.scheduler import parse_schedule


def generate_job_id() -> str:
    """Generate an 8-character cron job identifier."""
    return uuid.uuid4().hex[:8]


def validate_job(job: CronJob, *, now: datetime | None = None) -> str | None:
    """Validate a cron job schedule.

    Args:
        job: Job to validate.
        now: Optional timestamp used by scheduler parsing in tests.

    Returns:
        Error message when invalid, otherwise None.
    """
    next_run = parse_schedule(job, now=now)
    if next_run is None:
        return f"Invalid schedule '{job.schedule}'. Use cron syntax or 'every N'."
    return None


def add_job(jobs: list[CronJob], job: CronJob, *, now: datetime | None = None) -> list[CronJob]:
    """Return a new job list with a validated job appended.

    Args:
        jobs: Existing job list.
        job: New job to add.
        now: Optional timestamp used by scheduler parsing in tests.

    Returns:
        New list with the appended job.

    Raises:
        ValueError: If job validation fails.
    """
    error = validate_job(job, now=now)
    if error is not None:
        raise ValueError(error)
    return [*jobs, job]


def remove_job(jobs: list[CronJob], job_id: str) -> tuple[list[CronJob], bool]:
    """Return a new list with a job removed by ID."""
    updated = [job for job in jobs if job.id != job_id]
    return updated, len(updated) != len(jobs)


def set_enabled(jobs: list[CronJob], job_id: str, enabled: bool) -> tuple[list[CronJob], bool]:
    """Return a new list with one job's enabled flag updated."""
    updated: list[CronJob] = []
    found = False
    for job in jobs:
        if job.id != job_id:
            updated.append(job)
            continue
        found = True
        updated.append(
            CronJob(
                id=job.id,
                name=job.name,
                message=job.message,
                schedule=job.schedule,
                channel=job.channel,
                enabled=enabled,
                timezone=job.timezone,
                last_run=job.last_run,
                metadata=dict(job.metadata),
            )
        )
    return updated, found


def format_jobs(jobs: list[CronJob]) -> str:
    """Render cron jobs using the shared CLI-compatible text layout."""
    if not jobs:
        return "No cron jobs configured."

    lines: list[str] = []
    for job in jobs:
        state = "on" if job.enabled else "off"
        lines.append(f"  [{state}] {job.id}  {job.name}")
        lines.append(
            f"       schedule: {job.schedule}  timezone: {job.timezone}  channel: {job.channel}"
        )
        lines.append(f"       message:  {job.message}")
    return "\n".join(lines)
