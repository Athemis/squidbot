"""Cron subcommands for squidbot CLI.

Provides commands to list, add, and remove scheduled jobs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import cyclopts

from squidbot.config.schema import DEFAULT_CONFIG_PATH

cron_app = cyclopts.App(name="cron", help="Manage scheduled jobs.")


@cron_app.command
def list_jobs(config: Path = DEFAULT_CONFIG_PATH) -> None:
    """List all scheduled cron jobs."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory

    async def _list() -> None:
        storage = JsonlMemory(base_dir=Path.home() / ".squidbot")
        jobs = await storage.load_cron_jobs()
        from squidbot.core.cron_ops import format_jobs  # noqa: PLC0415

        print(format_jobs(jobs))

    asyncio.run(_list())


@cron_app.command
def add(
    name: str,
    message: str,
    schedule: str,
    channel: str = "cli:local",
    config: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Add a new cron job."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.core.models import CronJob

    async def _add() -> None:
        storage = JsonlMemory(base_dir=Path.home() / ".squidbot")
        from squidbot.core.cron_ops import add_job, generate_job_id  # noqa: PLC0415

        jobs = await storage.load_cron_jobs()
        job = CronJob(
            id=generate_job_id(),
            name=name,
            message=message,
            schedule=schedule,
            channel=channel,
        )
        try:
            updated = add_job(jobs, job)
        except ValueError as exc:
            print(f"Error: {exc}")
            raise SystemExit(2) from exc
        await storage.save_cron_jobs(updated)
        print(f"Added cron job '{name}' (id={job.id})")

    asyncio.run(_add())


@cron_app.command
def remove(job_id: str, config: Path = DEFAULT_CONFIG_PATH) -> None:
    """Remove a cron job by ID."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory

    async def _remove() -> None:
        storage = JsonlMemory(base_dir=Path.home() / ".squidbot")
        from squidbot.core.cron_ops import remove_job  # noqa: PLC0415

        jobs = await storage.load_cron_jobs()
        updated, removed = remove_job(jobs, job_id)
        if not removed:
            print(f"No job found with id '{job_id}'")
            return
        await storage.save_cron_jobs(updated)
        print(f"Removed job '{job_id}'")

    asyncio.run(_remove())
