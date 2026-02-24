"""Cron subcommands for squidbot CLI.

Provides commands to list, add, and remove scheduled jobs.
"""

from __future__ import annotations

import asyncio
import uuid
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
        if not jobs:
            print("No cron jobs configured.")
            return
        for job in jobs:
            state = "on" if job.enabled else "off"
            print(f"  [{state}] {job.id}  {job.name}")
            print(f"       schedule: {job.schedule}  channel: {job.channel}")
            print(f"       message:  {job.message}")

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
        jobs = await storage.load_cron_jobs()
        job = CronJob(
            id=str(uuid.uuid4())[:8],
            name=name,
            message=message,
            schedule=schedule,
            channel=channel,
        )
        jobs.append(job)
        await storage.save_cron_jobs(jobs)
        print(f"Added cron job '{name}' (id={job.id})")

    asyncio.run(_add())


@cron_app.command
def remove(job_id: str, config: Path = DEFAULT_CONFIG_PATH) -> None:
    """Remove a cron job by ID."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory

    async def _remove() -> None:
        storage = JsonlMemory(base_dir=Path.home() / ".squidbot")
        jobs = await storage.load_cron_jobs()
        before = len(jobs)
        jobs = [j for j in jobs if j.id != job_id]
        if len(jobs) == before:
            print(f"No job found with id '{job_id}'")
            return
        await storage.save_cron_jobs(jobs)
        print(f"Removed job '{job_id}'")

    asyncio.run(_remove())
