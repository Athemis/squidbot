"""Smoke checks for packaged dashboard assets in installed environments.

This module verifies that installed artifacts can serve bundled dashboard static
assets through the default app factory. It runs in dedicated packaging CI to
catch wheel-distribution regressions early.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from squidbot.adapters.dashboard.api import build_dashboard_app

pytestmark = pytest.mark.skipif(
    os.environ.get("SQUIDBOT_RUN_PACKAGING_SMOKE") != "1",
    reason="Packaging smoke test runs only in dedicated packaging jobs",
)


def test_installed_package_serves_dashboard_index() -> None:
    """Installed wheel should include and serve dashboard static index."""
    client = TestClient(build_dashboard_app())
    response = client.get("/")

    assert response.status_code == 200
    assert '<div id="app"' in response.text
