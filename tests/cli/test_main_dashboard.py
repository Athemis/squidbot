"""Validate gateway CLI command wiring in squidbot.

This module verifies command wiring after dashboard startup became config-driven
under the gateway command.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch


def test_gateway_command_runs_gateway_without_dashboard_flag() -> None:
    """gateway() wires logging and gateway startup without extra flags."""
    from squidbot.cli import main

    config_path = Path("/tmp/squidbot-gateway.json")

    with (
        patch("squidbot.cli.main._setup_logging") as setup_logging,
        patch("squidbot.cli.main.asyncio.run") as asyncio_run,
        patch(
            "squidbot.cli.main._run_gateway", new=Mock(return_value="gateway-coro")
        ) as run_gateway,
    ):
        main.gateway(config=config_path, log_level="DEBUG")

    setup_logging.assert_called_once_with("DEBUG")
    run_gateway.assert_called_once_with(config_path=config_path)
    asyncio_run.assert_called_once_with("gateway-coro")


def test_main_module_has_no_dashboard_command_function() -> None:
    """main module should no longer expose a dashboard command entrypoint."""
    from squidbot.cli import main

    assert not hasattr(main, "dashboard")
