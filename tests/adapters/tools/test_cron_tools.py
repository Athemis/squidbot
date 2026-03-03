"""Tests for cron management agent tools."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from squidbot.adapters.persistence.jsonl import JsonlMemory
from squidbot.adapters.tools.cron import (
    CronAddTool,
    CronListTool,
    CronRemoveTool,
    CronSetEnabledTool,
)
from squidbot.core.models import CronJob
from squidbot.core.scheduler import CronScheduler


def _storage(tmp_path: Path) -> JsonlMemory:
    return JsonlMemory(base_dir=tmp_path)


class TestCronAddTool:
    async def test_add_uses_email_defaults_and_sets_subject(self, tmp_path: Path) -> None:
        storage = _storage(tmp_path)
        tool = CronAddTool(
            storage=storage,
            default_channel="email:user@example.com",
            default_metadata={"email_subject": "Ignored"},
        )

        result = await tool.execute(
            name="Daily reminder",
            message="Drink water",
            schedule="0 9 * * *",
        )

        assert not result.is_error
        assert result.content.startswith("OK: created cron job id=")
        jobs = await storage.load_cron_jobs()
        assert len(jobs) == 1
        assert jobs[0].channel == "email:user@example.com"
        assert jobs[0].timezone == "local"
        assert jobs[0].metadata == {"email_subject": "[squidbot] Daily reminder"}

    async def test_add_matrix_requires_room_id(self, tmp_path: Path) -> None:
        storage = _storage(tmp_path)
        tool = CronAddTool(
            storage=storage,
            default_channel="matrix:@alex:matrix.org",
            default_metadata={},
        )

        result = await tool.execute(
            name="Matrix reminder",
            message="Ping",
            schedule="0 9 * * *",
        )

        assert result.is_error
        assert "matrix_room_id" in result.content

    async def test_add_matrix_stores_thread_metadata(self, tmp_path: Path) -> None:
        storage = _storage(tmp_path)
        tool = CronAddTool(
            storage=storage,
            default_channel="matrix:@alex:matrix.org",
            default_metadata={
                "matrix_room_id": "!room:matrix.org",
                "matrix_thread_root": "$root",
            },
        )

        result = await tool.execute(
            name="Matrix reminder",
            message="Ping",
            schedule="0 9 * * *",
        )

        assert not result.is_error
        jobs = await storage.load_cron_jobs()
        assert jobs[0].metadata == {
            "matrix_room_id": "!room:matrix.org",
            "matrix_thread_root": "$root",
        }

    async def test_add_from_cli_requires_explicit_channel(self, tmp_path: Path) -> None:
        storage = _storage(tmp_path)
        tool = CronAddTool(storage=storage, default_channel="cli:local", default_metadata={})

        result = await tool.execute(name="CLI reminder", message="Ping", schedule="every 60")

        assert result.is_error
        assert "channel is required" in result.content


class TestCronListRemoveSetEnabled:
    async def test_list_remove_and_toggle(self, tmp_path: Path) -> None:
        storage = _storage(tmp_path)
        jobs = [
            CronJob(
                id="abc12345",
                name="Morning",
                message="Hi",
                schedule="0 9 * * *",
                channel="email:user@example.com",
                enabled=True,
                timezone="local",
            )
        ]
        await storage.save_cron_jobs(jobs)

        list_tool = CronListTool(storage=storage)
        list_result = await list_tool.execute()
        assert not list_result.is_error
        assert "[on] abc12345  Morning" in list_result.content

        toggle_tool = CronSetEnabledTool(storage=storage)
        toggle_result = await toggle_tool.execute(job_id="abc12345", enabled=False)
        assert not toggle_result.is_error

        remove_tool = CronRemoveTool(storage=storage)
        remove_result = await remove_tool.execute(job_id="abc12345")
        assert not remove_result.is_error

        final_jobs = await storage.load_cron_jobs()
        assert final_jobs == []


class TestCronToolConcurrency:
    async def test_tick_allows_on_due_to_mutate_cron_jobs_with_shared_lock(self) -> None:
        class InMemoryStorage:
            def __init__(self, jobs: list[CronJob]) -> None:
                self.jobs = list(jobs)

            async def load_cron_jobs(self) -> list[CronJob]:
                return list(self.jobs)

            async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
                self.jobs = list(jobs)

        now = datetime.now(UTC)
        due_job = CronJob(
            id="duejob01",
            name="Due",
            message="Run",
            schedule="every 1",
            channel="email:user@example.com",
            last_run=None,
        )
        removable_job = CronJob(
            id="deljob01",
            name="Delete me",
            message="Later",
            schedule="every 3600",
            channel="email:user@example.com",
            last_run=now,
        )
        storage = InMemoryStorage([due_job, removable_job])
        mutation_lock = asyncio.Lock()

        scheduler = CronScheduler(  # type: ignore[arg-type]
            storage=storage,
            mutation_lock=mutation_lock,
        )
        remove_tool = CronRemoveTool(  # type: ignore[arg-type]
            storage=storage,
            mutation_lock=mutation_lock,
        )

        async def on_due(job: CronJob) -> None:
            remove_result = await remove_tool.execute(job_id="deljob01")
            assert not remove_result.is_error

        await asyncio.wait_for(scheduler._tick(on_due), timeout=0.2)

        saved_jobs = await storage.load_cron_jobs()
        assert [job.id for job in saved_jobs] == ["duejob01"]

    async def test_remove_completes_while_scheduler_callback_waits(self) -> None:
        class InMemoryStorage:
            def __init__(self, jobs: list[CronJob]) -> None:
                self.jobs = list(jobs)

            async def load_cron_jobs(self) -> list[CronJob]:
                return list(self.jobs)

            async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
                self.jobs = list(jobs)

        now = datetime.now(UTC)
        due_job = CronJob(
            id="duejob01",
            name="Due",
            message="Run",
            schedule="every 1",
            channel="email:user@example.com",
            last_run=None,
        )
        removable_job = CronJob(
            id="deljob01",
            name="Delete me",
            message="Later",
            schedule="every 3600",
            channel="email:user@example.com",
            last_run=now,
        )
        storage = InMemoryStorage([due_job, removable_job])
        mutation_lock = asyncio.Lock()

        scheduler = CronScheduler(  # type: ignore[arg-type]
            storage=storage,
            mutation_lock=mutation_lock,
        )
        remove_tool = CronRemoveTool(  # type: ignore[arg-type]
            storage=storage,
            mutation_lock=mutation_lock,
        )
        on_due_started = asyncio.Event()
        allow_on_due_finish = asyncio.Event()

        async def on_due(job: CronJob) -> None:
            on_due_started.set()
            await allow_on_due_finish.wait()

        tick_task = asyncio.create_task(scheduler._tick(on_due))
        await on_due_started.wait()

        remove_task = asyncio.create_task(remove_tool.execute(job_id="deljob01"))
        remove_result = await asyncio.wait_for(remove_task, timeout=0.2)
        assert not remove_result.is_error

        allow_on_due_finish.set()
        await tick_task

        saved_jobs = await storage.load_cron_jobs()
        assert [job.id for job in saved_jobs] == ["duejob01"]

    async def test_concurrent_mutations_complete_while_scheduler_callback_is_waiting(self) -> None:
        class InMemoryStorage:
            def __init__(self, jobs: list[CronJob]) -> None:
                self.jobs = list(jobs)

            async def load_cron_jobs(self) -> list[CronJob]:
                return list(self.jobs)

            async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
                self.jobs = list(jobs)

        now = datetime.now(UTC)
        due_job = CronJob(
            id="duejob01",
            name="Due",
            message="Run",
            schedule="every 1",
            channel="email:user@example.com",
            last_run=None,
        )
        removable_job = CronJob(
            id="deljob01",
            name="Delete me",
            message="Later",
            schedule="every 3600",
            channel="email:user@example.com",
            last_run=now,
        )
        toggle_job = CronJob(
            id="togjob01",
            name="Toggle me",
            message="Later",
            schedule="every 3600",
            channel="email:user@example.com",
            enabled=True,
            last_run=now,
        )
        storage = InMemoryStorage([due_job, removable_job, toggle_job])
        mutation_lock = asyncio.Lock()

        scheduler = CronScheduler(  # type: ignore[arg-type]
            storage=storage,
            mutation_lock=mutation_lock,
        )
        add_tool = CronAddTool(  # type: ignore[arg-type]
            storage=storage,
            default_channel="email:user@example.com",
            default_metadata={},
            mutation_lock=mutation_lock,
        )
        remove_tool = CronRemoveTool(  # type: ignore[arg-type]
            storage=storage,
            mutation_lock=mutation_lock,
        )
        toggle_tool = CronSetEnabledTool(  # type: ignore[arg-type]
            storage=storage,
            mutation_lock=mutation_lock,
        )
        on_due_started = asyncio.Event()
        allow_on_due_finish = asyncio.Event()

        async def on_due(job: CronJob) -> None:
            on_due_started.set()
            await allow_on_due_finish.wait()
            remove_result = await remove_tool.execute(job_id="deljob01")
            assert not remove_result.is_error

        tick_task = asyncio.create_task(scheduler._tick(on_due))
        await on_due_started.wait()

        toggle_task = asyncio.create_task(toggle_tool.execute(job_id="togjob01", enabled=False))
        add_task = asyncio.create_task(
            add_tool.execute(name="Added", message="New", schedule="every 600")
        )
        toggle_result, add_result = await asyncio.wait_for(
            asyncio.gather(toggle_task, add_task),
            timeout=0.2,
        )
        assert not toggle_result.is_error
        assert not add_result.is_error

        allow_on_due_finish.set()
        await asyncio.wait_for(tick_task, timeout=0.2)

        saved_jobs = await storage.load_cron_jobs()
        ids = {job.id for job in saved_jobs}
        assert "duejob01" in ids
        assert "deljob01" not in ids
        assert any(job.name == "Added" for job in saved_jobs)
        assert any(job.id == "togjob01" and not job.enabled for job in saved_jobs)
