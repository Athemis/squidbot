"""Tests for serving packaged dashboard frontend assets."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from squidbot.adapters.dashboard.api import build_dashboard_app
from squidbot.adapters.dashboard.logs import DashboardLogBuffer
from squidbot.adapters.dashboard.runtime import DashboardRuntime
from squidbot.core.models import GatewayState


def _runtime() -> DashboardRuntime:
    return DashboardRuntime(
        state=GatewayState(
            active_sessions={},
            channel_status=[],
            cron_jobs_cache=[],
            started_at=datetime(2026, 1, 1),
        ),
        log_buffer=DashboardLogBuffer(),
        config_path=None,
    )


def test_dashboard_root_serves_packaged_index_html(tmp_path: Path) -> None:
    """Root should serve packaged index.html when static assets exist."""
    static_dir = tmp_path / "static"
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text('<div id="app"></div>', encoding="utf-8")

    client = TestClient(build_dashboard_app(_runtime(), static_dir=static_dir))

    response = client.get("/")

    assert response.status_code == 200
    assert '<div id="app"></div>' in response.text


def test_dashboard_assets_route_serves_static_files(tmp_path: Path) -> None:
    """Mounted /assets route should serve packaged static files."""
    static_dir = tmp_path / "static"
    static_dir.mkdir(parents=True)
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text('<div id="app"></div>', encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ok')", encoding="utf-8")

    client = TestClient(build_dashboard_app(_runtime(), static_dir=static_dir))

    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert "console.log('ok')" in response.text


def test_dashboard_uses_default_package_static_dir_when_not_overridden(tmp_path: Path) -> None:
    """App should resolve static assets from package path by default."""
    static_dir = tmp_path / "pkg-static"
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text('<div id="app">pkg</div>', encoding="utf-8")

    with patch("squidbot.adapters.dashboard.api._default_static_dir", return_value=static_dir):
        client = TestClient(build_dashboard_app(_runtime()))
        response = client.get("/")

    assert response.status_code == 200
    assert "pkg" in response.text


def test_missing_packaged_assets_returns_clear_error(tmp_path: Path) -> None:
    """Root should return deterministic error when packaged assets are missing."""
    missing_dir = tmp_path / "missing"
    client = TestClient(build_dashboard_app(_runtime(), static_dir=missing_dir))

    response = client.get("/")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DASHBOARD_ASSETS_MISSING"
