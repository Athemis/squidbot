"""Tests for squidbot.cli.gateway helper functions."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from squidbot.cli.gateway import _print_banner, _setup_logging


def test_setup_logging_invalid_level_prints_error_and_exits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch("loguru.logger.remove"),
        patch("loguru.logger.add"),
        pytest.raises(SystemExit) as exc_info,
    ):
        _setup_logging("bad")

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "error: invalid --log-level 'bad'" in captured.err
    assert "Valid values:" in captured.err


def test_setup_logging_info_configures_loguru_handlers() -> None:
    with patch("loguru.logger.remove") as remove_mock, patch("loguru.logger.add") as add_mock:
        _setup_logging("info")

    remove_mock.assert_called_once_with()
    add_mock.assert_called_once()

    _, kwargs = add_mock.call_args
    assert kwargs["level"] == "INFO"
    assert kwargs["colorize"] is True
    assert "{time:YYYY-MM-DD HH:mm:ss}" in kwargs["format"]


def test_setup_logging_clamps_noisy_loggers_to_warning() -> None:
    logger_by_name = {
        name: MagicMock() for name in ("httpx", "nio", "aioimaplib", "aiosmtplib", "openai")
    }

    with (
        patch("loguru.logger.remove"),
        patch("loguru.logger.add"),
        patch(
            "logging.getLogger", side_effect=lambda name: logger_by_name[name]
        ) as get_logger_mock,
    ):
        _setup_logging("warning")

    assert get_logger_mock.call_count == 5
    for logger_mock in logger_by_name.values():
        logger_mock.setLevel.assert_called_once_with(logging.WARNING)


def test_print_banner_outputs_version_pool_and_workspace(
    capsys: pytest.CaptureFixture[str], tmp_path
) -> None:
    workspace = tmp_path / "workspace"
    settings = SimpleNamespace(
        llm=SimpleNamespace(default_pool="smart"),
        agents=SimpleNamespace(workspace=str(workspace)),
    )

    with patch("importlib.metadata.version", return_value="9.9.9"):
        _print_banner(settings)

    captured = capsys.readouterr()
    assert "squidbot v9.9.9" in captured.err
    assert "pool:      smart" in captured.err
    assert f"workspace: {workspace.resolve()}" in captured.err
