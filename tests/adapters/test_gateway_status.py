"""Tests for GatewayState and GatewayStatusAdapter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from squidbot.core.models import ChannelStatus, CronJob, SessionInfo
from squidbot.core.skills import SkillMetadata


async def _noop(*args: object, **kwargs: object) -> None:
    """Async no-op for test doubles."""


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


class TestChannelLoopWithState:
    async def test_first_message_creates_session_info(self) -> None:
        from squidbot.cli.main import GatewayState, _channel_loop_with_state
        from squidbot.core.models import InboundMessage, Session

        state = GatewayState(
            active_sessions={},
            channel_status=[],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1),
        )

        session = Session(channel="email", sender_id="user@example.com")
        inbound = InboundMessage(session=session, text="Hello")

        fake_loop = MagicMock()
        fake_loop.run = AsyncMock()

        async def fake_receive():  # type: ignore[return]
            yield inbound

        fake_channel = MagicMock()
        fake_channel.receive = fake_receive
        fake_storage = MagicMock()

        await _channel_loop_with_state(fake_channel, fake_loop, state, fake_storage)  # type: ignore[arg-type]

        assert "email:user@example.com" in state.active_sessions
        info = state.active_sessions["email:user@example.com"]
        assert info.message_count == 1
        assert info.channel == "email"
        assert info.sender_id == "user@example.com"

    async def test_second_message_increments_count(self) -> None:
        from squidbot.cli.main import GatewayState, _channel_loop_with_state
        from squidbot.core.models import InboundMessage, Session

        state = GatewayState(
            active_sessions={},
            channel_status=[],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1),
        )

        session = Session(channel="email", sender_id="user@example.com")
        msg1 = InboundMessage(session=session, text="First")
        msg2 = InboundMessage(session=session, text="Second")

        fake_loop = MagicMock()
        fake_loop.run = AsyncMock()

        async def fake_receive():  # type: ignore[return]
            yield msg1
            yield msg2

        fake_channel = MagicMock()
        fake_channel.receive = fake_receive
        fake_storage = MagicMock()

        await _channel_loop_with_state(fake_channel, fake_loop, state, fake_storage)  # type: ignore[arg-type]

        assert state.active_sessions["email:user@example.com"].message_count == 2
