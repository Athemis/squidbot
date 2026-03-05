"""Tests for dashboard server configuration schema.

This module validates loopback-only host constraints and default dashboard
network settings in `Settings`. It protects the local-only security posture of
the dashboard feature during configuration loading.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from squidbot.config.schema import Settings


def test_dashboard_settings_defaults_to_loopback() -> None:
    """Dashboard defaults should be local-only with a deterministic port."""
    settings = Settings()

    assert settings.dashboard.host == "127.0.0.1"
    assert settings.dashboard.port == 8765


def test_dashboard_settings_reject_non_loopback_host() -> None:
    """Dashboard host must remain loopback-only in v1."""
    with pytest.raises(ValidationError):
        Settings.model_validate({"dashboard": {"host": "0.0.0.0"}})


def test_dashboard_settings_accept_ipv6_loopback_host() -> None:
    """Dashboard host accepts IPv6 loopback literals."""
    settings = Settings.model_validate({"dashboard": {"host": "::1"}})

    assert settings.dashboard.host == "::1"
