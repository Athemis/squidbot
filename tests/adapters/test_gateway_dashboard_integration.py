"""Integration-oriented tests for gateway dashboard lifecycle wiring."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


def _build_settings() -> SimpleNamespace:
    return SimpleNamespace(
        channels=SimpleNamespace(
            matrix=SimpleNamespace(enabled=False),
            email=SimpleNamespace(enabled=False),
        ),
        agents=SimpleNamespace(
            workspace="/tmp/squidbot-test-workspace",
            restrict_to_workspace=False,
            heartbeat=SimpleNamespace(
                enabled=False,
                interval_minutes=30,
                active_hours_start="00:00",
                active_hours_end="24:00",
                timezone="local",
                pool=None,
            ),
        ),
        llm=SimpleNamespace(default_pool="default"),
        owner=SimpleNamespace(aliases=[]),
        dashboard=SimpleNamespace(enabled=True, host="127.0.0.1", port=8765),
    )


def test_dashboard_settings_falls_back_to_defaults_when_missing() -> None:
    from squidbot.cli.gateway import _dashboard_settings

    settings: Any = SimpleNamespace()

    dashboard = _dashboard_settings(settings)

    assert dashboard.enabled is False
    assert dashboard.host == "127.0.0.1"
    assert dashboard.port == 8765


def test_dashboard_settings_uses_configured_values() -> None:
    from squidbot.cli.gateway import _dashboard_settings

    settings: Any = SimpleNamespace(
        dashboard=SimpleNamespace(enabled=True, host="localhost", port=9000)
    )

    dashboard = _dashboard_settings(settings)

    assert dashboard.enabled is True
    assert dashboard.host == "localhost"
    assert dashboard.port == 9000


async def test_run_dashboard_server_uses_uvicorn_config_and_serves() -> None:
    from squidbot.cli.gateway import _run_dashboard_server

    runtime = object()
    settings: Any = _build_settings()
    fake_server = MagicMock()
    fake_server.serve = AsyncMock(return_value=None)

    with (
        patch(
            "squidbot.adapters.dashboard.api.build_dashboard_app", return_value="app"
        ) as build_app,
        patch("uvicorn.Config", return_value="config") as uvicorn_config,
        patch("uvicorn.Server", return_value=fake_server) as uvicorn_server,
    ):
        await _run_dashboard_server(runtime, settings)

    build_app.assert_called_once_with(runtime)
    uvicorn_config.assert_called_once_with(
        app="app",
        host="127.0.0.1",
        port=8765,
        log_level="warning",
    )
    uvicorn_server.assert_called_once_with("config")
    fake_server.serve.assert_awaited_once_with()


async def _block_forever(*args: object, **kwargs: object) -> None:
    await asyncio.Event().wait()


async def test_run_gateway_starts_dashboard_server_and_stops_on_shutdown() -> None:
    from squidbot.cli.gateway import _run_gateway

    settings = _build_settings()
    fake_loop = MagicMock()
    fake_loop.run = AsyncMock()
    fake_conn = MagicMock()
    fake_conn.close = AsyncMock()
    fake_storage = MagicMock()
    fake_storage.load_cron_jobs = AsyncMock(return_value=[])

    scheduler = MagicMock()
    scheduler.run = AsyncMock(side_effect=_block_forever)
    heartbeat = MagicMock()
    heartbeat.run = AsyncMock(side_effect=_block_forever)
    dashboard_server = AsyncMock(side_effect=_block_forever)

    shutdown_event = asyncio.Event()

    async def _trigger_shutdown() -> None:
        await asyncio.sleep(0.05)
        shutdown_event.set()

    with (
        patch("squidbot.config.schema.Settings.load", return_value=settings),
        patch("squidbot.cli.gateway._print_banner"),
        patch(
            "squidbot.cli.gateway._make_agent_loop",
            new=AsyncMock(return_value=(fake_loop, [fake_conn], fake_storage)),
        ),
        patch("squidbot.core.scheduler.CronScheduler", return_value=scheduler),
        patch("squidbot.core.heartbeat.HeartbeatService", return_value=heartbeat),
        patch("squidbot.cli.gateway._run_dashboard_server", new=dashboard_server),
        patch("squidbot.cli.gateway.logger.add", return_value=42) as logger_add,
        patch("squidbot.cli.gateway.logger.remove") as logger_remove,
    ):
        await asyncio.gather(
            _trigger_shutdown(),
            asyncio.wait_for(
                _run_gateway(Path("/tmp/squidbot.yaml"), shutdown_event=shutdown_event),
                timeout=2.0,
            ),
        )

    dashboard_server.assert_awaited_once()
    logger_add.assert_called_once()
    logger_remove.assert_called_once_with(42)
    fake_conn.close.assert_awaited_once_with()


async def test_run_gateway_does_not_start_dashboard_server_when_disabled() -> None:
    from squidbot.cli.gateway import _run_gateway

    settings = _build_settings()
    settings.dashboard.enabled = False
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
    dashboard_server = AsyncMock(return_value=None)

    with (
        patch("squidbot.config.schema.Settings.load", return_value=settings),
        patch("squidbot.cli.gateway._print_banner"),
        patch(
            "squidbot.cli.gateway._make_agent_loop",
            new=AsyncMock(return_value=(fake_loop, [fake_conn], fake_storage)),
        ),
        patch("squidbot.core.scheduler.CronScheduler", return_value=scheduler),
        patch("squidbot.core.heartbeat.HeartbeatService", return_value=heartbeat),
        patch("squidbot.cli.gateway._run_dashboard_server", new=dashboard_server),
        patch("squidbot.cli.gateway.logger.add") as logger_add,
    ):
        await _run_gateway(Path("/tmp/squidbot.yaml"))

    dashboard_server.assert_not_awaited()
    logger_add.assert_not_called()
    fake_conn.close.assert_awaited_once_with()
