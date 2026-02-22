"""Tests for GatewayState and GatewayStatusAdapter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from squidbot.core.models import ChannelStatus, CronJob, SessionInfo
from squidbot.core.skills import SkillMetadata


class TestGatewayStatusAdapter:
    def test_get_active_sessions_empty(self) -> None:
        from squidbot.cli.main import GatewayState, GatewayStatusAdapter

        state = GatewayState(
            active_sessions={},
            channel_status=[],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1),
        )
        adapter = GatewayStatusAdapter(state=state, skills_loader=MagicMock())
        assert adapter.get_active_sessions() == []

    def test_get_active_sessions_returns_values(self) -> None:
        from squidbot.cli.main import GatewayState, GatewayStatusAdapter

        info = SessionInfo(
            session_id="email:user@example.com",
            channel="email",
            sender_id="user@example.com",
            started_at=datetime(2026, 1, 1),
            message_count=2,
        )
        state = GatewayState(
            active_sessions={"email:user@example.com": info},
            channel_status=[],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1),
        )
        adapter = GatewayStatusAdapter(state=state, skills_loader=MagicMock())
        assert adapter.get_active_sessions() == [info]

    def test_get_channel_status(self) -> None:
        from squidbot.cli.main import GatewayState, GatewayStatusAdapter

        cs = ChannelStatus(name="matrix", enabled=True, connected=True)
        state = GatewayState(
            active_sessions={},
            channel_status=[cs],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1),
        )
        adapter = GatewayStatusAdapter(state=state, skills_loader=MagicMock())
        assert adapter.get_channel_status() == [cs]

    def test_get_cron_jobs(self) -> None:
        from squidbot.cli.main import GatewayState, GatewayStatusAdapter

        job = CronJob(
            id="j1",
            name="Daily",
            message="check",
            schedule="0 9 * * *",
            channel="cli:local",
        )
        state = GatewayState(
            active_sessions={},
            channel_status=[],
            cron_jobs_cache=[job],
            started_at=datetime(2026, 1, 1),
        )
        adapter = GatewayStatusAdapter(state=state, skills_loader=MagicMock())
        assert adapter.get_cron_jobs() == [job]

    def test_get_skills_delegates_to_loader(self) -> None:
        from squidbot.cli.main import GatewayState, GatewayStatusAdapter

        skill = SkillMetadata(
            name="git",
            description="Git operations",
            location=Path("/skills/git/SKILL.md"),
        )
        loader = MagicMock()
        loader.list_skills.return_value = [skill]
        state = GatewayState(
            active_sessions={},
            channel_status=[],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1),
        )
        adapter = GatewayStatusAdapter(state=state, skills_loader=loader)
        assert adapter.get_skills() == [skill]
        loader.list_skills.assert_called_once()
