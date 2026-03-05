"""Security and bootstrap tests for dashboard API guards."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from squidbot.adapters.dashboard.api import build_dashboard_app
from squidbot.adapters.dashboard.logs import DashboardLogBuffer
from squidbot.adapters.dashboard.runtime import DashboardRuntime
from squidbot.config.schema import Settings
from squidbot.core.models import GatewayState


def _runtime() -> DashboardRuntime:
    state = GatewayState(
        active_sessions={},
        channel_status=[],
        cron_jobs_cache=[],
        started_at=datetime(2026, 1, 1),
    )
    return DashboardRuntime(state=state, log_buffer=DashboardLogBuffer(), config_path=None)


def _runtime_with_config(tmp_path) -> DashboardRuntime:
    runtime = _runtime()
    config_path = tmp_path / "config.json"
    Settings().save(config_path)
    runtime.config_path = config_path
    return runtime


def test_bootstrap_returns_local_nonce() -> None:
    """Bootstrap endpoint should expose the per-runtime local nonce."""
    runtime = _runtime()
    client = TestClient(build_dashboard_app(runtime))

    response = client.get("/api/bootstrap", headers={"host": "localhost"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["local_nonce"] == runtime.local_nonce
    assert isinstance(payload["local_nonce"], str)
    assert payload["local_nonce"]


def test_bootstrap_rejects_non_loopback_host() -> None:
    """Bootstrap should reject non-loopback host values."""
    runtime = _runtime()
    client = TestClient(build_dashboard_app(runtime))

    response = client.get("/api/bootstrap", headers={"host": "example.com"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INVALID_HOST"


def test_patch_config_rejects_missing_nonce() -> None:
    """Mutating config route should reject requests without local nonce."""
    runtime = _runtime()
    client = TestClient(build_dashboard_app(runtime))

    response = client.patch(
        "/api/config",
        json={},
        headers={"host": "localhost", "origin": "http://localhost"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "MISSING_NONCE"


def test_patch_config_rejects_non_loopback_origin() -> None:
    """Mutating route should reject non-loopback origin values."""
    runtime = _runtime()
    client = TestClient(build_dashboard_app(runtime))

    response = client.patch(
        "/api/config",
        json={},
        headers={
            "host": "localhost",
            "origin": "https://evil.example",
            "x-squidbot-local-nonce": runtime.local_nonce,
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INVALID_ORIGIN"


def test_patch_config_rejects_non_loopback_host() -> None:
    """Mutating route should reject non-loopback host values."""
    runtime = _runtime()
    client = TestClient(build_dashboard_app(runtime))

    response = client.patch(
        "/api/config",
        json={},
        headers={
            "host": "example.com",
            "origin": "http://localhost",
            "x-squidbot-local-nonce": runtime.local_nonce,
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INVALID_HOST"


def test_patch_config_rejects_invalid_nonce() -> None:
    """Mutating route should reject incorrect local nonce values."""
    runtime = _runtime()
    client = TestClient(build_dashboard_app(runtime))

    response = client.patch(
        "/api/config",
        json={},
        headers={
            "host": "localhost",
            "origin": "http://localhost",
            "x-squidbot-local-nonce": "wrong",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INVALID_NONCE"


def test_patch_config_accepts_loopback_origin_with_valid_nonce(tmp_path) -> None:
    """Guard should allow loopback writes when all local checks pass."""
    runtime = _runtime_with_config(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.patch(
        "/api/config",
        json={},
        headers={
            "host": "localhost",
            "origin": "http://localhost",
            "x-squidbot-local-nonce": runtime.local_nonce,
        },
    )

    assert response.status_code == 200


def test_patch_config_accepts_ipv6_loopback(tmp_path) -> None:
    """Guard should allow IPv6 loopback host and origin values."""
    runtime = _runtime_with_config(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.patch(
        "/api/config",
        json={},
        headers={
            "host": "[::1]:8765",
            "origin": "http://[::1]:8765",
            "x-squidbot-local-nonce": runtime.local_nonce,
        },
    )

    assert response.status_code == 200


def test_restart_intent_rejects_missing_nonce(tmp_path) -> None:
    """Restart intent must require local nonce on mutating route."""
    runtime = _runtime_with_config(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.post(
        "/api/config/restart-intent",
        headers={"host": "localhost", "origin": "http://localhost"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "MISSING_NONCE"


def test_restart_intent_rejects_non_loopback_host(tmp_path) -> None:
    """Restart intent should reject non-loopback host values."""
    runtime = _runtime_with_config(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.post(
        "/api/config/restart-intent",
        headers={
            "host": "evil.example",
            "origin": "http://localhost",
            "x-squidbot-local-nonce": runtime.local_nonce,
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INVALID_HOST"
