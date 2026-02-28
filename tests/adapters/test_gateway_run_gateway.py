"""Tests for squidbot.cli.gateway._run_gateway execution flow."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from squidbot.core.models import CronJob, Session


def _build_settings(*, matrix_enabled: bool, email_enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(
        channels=SimpleNamespace(
            matrix=SimpleNamespace(enabled=matrix_enabled),
            email=SimpleNamespace(enabled=email_enabled),
        ),
        agents=SimpleNamespace(
            workspace="/tmp/squidbot-test-workspace",
            heartbeat=SimpleNamespace(
                enabled=False,
                interval_minutes=30,
                active_hours_start="08:00",
                active_hours_end="22:00",
                timezone="local",
                pool=None,
            ),
        ),
        llm=SimpleNamespace(default_pool="default"),
    )


async def test_run_gateway_with_all_channels_disabled_completes_and_closes_connections() -> None:
    from squidbot.cli.gateway import _run_gateway

    settings = _build_settings(matrix_enabled=False, email_enabled=False)
    fake_loop = MagicMock()
    fake_loop.run = AsyncMock()
    fake_conn = MagicMock()
    fake_conn.close = AsyncMock()
    fake_storage = MagicMock()
    fake_storage.load_cron_jobs = AsyncMock(return_value=[])

    scheduler = MagicMock()
    scheduler.run = AsyncMock(return_value=None)
    heartbeat = MagicMock()
    heartbeat.run = AsyncMock(return_value=None)

    with (
        patch("squidbot.config.schema.Settings.load", return_value=settings),
        patch("squidbot.cli.gateway._print_banner"),
        patch(
            "squidbot.cli.gateway._make_agent_loop",
            new=AsyncMock(return_value=(fake_loop, [fake_conn], fake_storage)),
        ) as make_agent_loop,
        patch("squidbot.core.scheduler.CronScheduler", return_value=scheduler),
        patch("squidbot.core.heartbeat.HeartbeatService", return_value=heartbeat),
    ):
        await _run_gateway(Path("/tmp/squidbot.yaml"))

    make_agent_loop.assert_awaited_once_with(settings)
    scheduler.run.assert_awaited_once()
    heartbeat.run.assert_awaited_once_with()
    fake_loop.run.assert_not_awaited()
    fake_conn.close.assert_awaited_once_with()


async def test_run_gateway_delivers_due_cron_job_to_matrix_channel() -> None:
    from squidbot.cli.gateway import _run_gateway

    settings = _build_settings(matrix_enabled=True, email_enabled=False)
    delivered = asyncio.Event()

    async def run_side_effect(*args: object, **kwargs: object) -> None:
        delivered.set()

    fake_loop = MagicMock()
    fake_loop.run = AsyncMock(side_effect=run_side_effect)
    fake_conn = MagicMock()
    fake_conn.close = AsyncMock()
    cron_job = CronJob(
        id="job-1",
        name="Ping",
        message="scheduled hello",
        schedule="every 60",
        channel="matrix:@alice:matrix.org",
        metadata={"thread": "abc"},
    )
    fake_storage = MagicMock()
    fake_storage.load_cron_jobs = AsyncMock(return_value=[cron_job])

    scheduler = MagicMock()

    async def scheduler_run_side_effect(*, on_due: object) -> None:
        assert callable(on_due)
        await on_due(cron_job)

    scheduler.run = AsyncMock(side_effect=scheduler_run_side_effect)
    heartbeat = MagicMock()
    heartbeat.run = AsyncMock(return_value=None)
    matrix_channel = MagicMock()

    with (
        patch("squidbot.config.schema.Settings.load", return_value=settings),
        patch("squidbot.cli.gateway._print_banner"),
        patch(
            "squidbot.cli.gateway._make_agent_loop",
            new=AsyncMock(return_value=(fake_loop, [fake_conn], fake_storage)),
        ),
        patch("squidbot.core.scheduler.CronScheduler", return_value=scheduler),
        patch("squidbot.core.heartbeat.HeartbeatService", return_value=heartbeat),
        patch("squidbot.adapters.channels.matrix.MatrixChannel", return_value=matrix_channel),
        patch(
            "squidbot.cli.gateway._channel_loop_with_state",
            new=AsyncMock(return_value=None),
        ),
    ):
        await _run_gateway(Path("/tmp/squidbot.yaml"))

    assert delivered.is_set()
    fake_loop.run.assert_awaited_once()
    args = fake_loop.run.await_args.args
    kwargs = fake_loop.run.await_args.kwargs
    assert isinstance(args[0], Session)
    assert args[0].channel == "matrix"
    assert args[0].sender_id == "@alice:matrix.org"
    assert args[1] == "scheduled hello"
    assert args[2] is matrix_channel
    assert kwargs["outbound_metadata"] == {"thread": "abc"}
    fake_conn.close.assert_awaited_once_with()
