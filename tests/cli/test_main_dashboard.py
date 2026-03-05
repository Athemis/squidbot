"""Validate dashboard CLI command wiring in squidbot.

This module verifies that the command configures logging and invokes gateway
startup with dashboard mode enabled. It protects the CLI-to-runtime contract
for the local web dashboard entrypoint.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch


def test_dashboard_command_runs_gateway_with_dashboard_enabled() -> None:
    """dashboard() wires logging and gateway startup with dashboard mode."""
    from squidbot.cli import main

    config_path = Path("/tmp/squidbot-dashboard.json")

    with (
        patch("squidbot.cli.main._setup_logging") as setup_logging,
        patch("squidbot.cli.main.asyncio.run") as asyncio_run,
        patch(
            "squidbot.cli.main._run_gateway", new=Mock(return_value="gateway-coro")
        ) as run_gateway,
    ):
        main.dashboard(config=config_path, log_level="DEBUG")

    setup_logging.assert_called_once_with("DEBUG")
    run_gateway.assert_called_once_with(config_path=config_path, dashboard_enabled=True)
    asyncio_run.assert_called_once_with("gateway-coro")
