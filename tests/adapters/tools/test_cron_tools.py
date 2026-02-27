"""Tests for cron management agent tools."""

from __future__ import annotations

from pathlib import Path

from squidbot.adapters.persistence.jsonl import JsonlMemory
from squidbot.adapters.tools.cron import (
    CronAddTool,
    CronListTool,
    CronRemoveTool,
    CronSetEnabledTool,
)
from squidbot.core.models import CronJob


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
