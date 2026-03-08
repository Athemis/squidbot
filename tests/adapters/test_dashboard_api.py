"""Tests for dashboard core JSON API endpoints."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from squidbot.adapters.dashboard.api import build_dashboard_app
from squidbot.adapters.dashboard.logs import DashboardLogBuffer
from squidbot.adapters.dashboard.runtime import DashboardRuntime
from squidbot.config.schema import Settings
from squidbot.core.models import ChannelStatus, GatewayState, SessionInfo


def _headers(runtime: DashboardRuntime) -> dict[str, str]:
    return {
        "host": "localhost",
        "origin": "http://localhost",
        "x-squidbot-local-nonce": runtime.local_nonce,
    }


def _runtime(tmp_path: Path) -> DashboardRuntime:
    config_path = tmp_path / "config.json"
    settings = Settings()
    settings.channels.matrix.enabled = True
    settings.channels.email.enabled = False
    settings.agents.heartbeat.enabled = True
    settings.agents.heartbeat.interval_minutes = 30
    settings.save(config_path)

    state = GatewayState(
        active_sessions={
            "email:user@example.com": SessionInfo(
                session_id="email:user@example.com",
                channel="email",
                sender_id="user@example.com",
                started_at=datetime(2026, 1, 1),
                message_count=3,
            )
        },
        channel_status=[ChannelStatus(name="email", enabled=True, connected=True)],
        cron_jobs_cache=[],
        started_at=datetime(2026, 1, 1),
    )
    log_buffer = DashboardLogBuffer(max_entries=20)
    for idx in range(5):
        log_buffer.append(level="INFO", message=f"line-{idx}")
    return DashboardRuntime(state=state, log_buffer=log_buffer, config_path=config_path)


def test_get_overview_returns_channels_and_sessions(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.get("/api/overview", headers={"host": "localhost"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["channels"][0]["name"] == "email"
    assert payload["active_sessions"][0]["session_id"] == "email:user@example.com"


def test_get_logs_returns_paginated_entries(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.get("/api/logs?limit=2", headers={"host": "localhost"})

    assert response.status_code == 200
    payload = response.json()
    assert [entry["message"] for entry in payload["entries"]] == ["line-3", "line-4"]
    assert payload["next_before_cursor"] is not None


def test_get_logs_invalid_limit_returns_generic_validation_message(tmp_path: Path) -> None:
    """Logs endpoint should not expose raw exception messages to clients."""
    runtime = _runtime(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.get("/api/logs?limit=0", headers={"host": "localhost"})

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Invalid log pagination parameters.",
        }
    }


def test_get_config_returns_editable_projection(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.get("/api/config", headers={"host": "localhost"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["channels"]["matrix_enabled"] is True
    assert payload["channels"]["email_enabled"] is False
    assert payload["heartbeat"]["interval_minutes"] == 30


def test_patch_config_updates_allowed_fields_and_marks_restart_required(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.patch(
        "/api/config",
        json={"channels": {"email_enabled": True}, "heartbeat": {"interval_minutes": 45}},
        headers=_headers(runtime),
    )

    assert response.status_code == 200
    assert response.json() == {"saved": True, "restart_required": True}

    assert runtime.config_path is not None
    saved = Settings.load(runtime.config_path)
    assert saved.channels.email.enabled is True
    assert saved.agents.heartbeat.interval_minutes == 45


def test_patch_config_rejects_unknown_fields(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.patch(
        "/api/config",
        json={"channels": {"unknown": True}},
        headers=_headers(runtime),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_patch_config_rejects_boolean_interval_minutes(tmp_path: Path) -> None:
    """interval_minutes must reject bool values even though bool is int-like."""
    runtime = _runtime(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.patch(
        "/api/config",
        json={"heartbeat": {"interval_minutes": True}},
        headers=_headers(runtime),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_patch_config_rejects_malformed_json_payload(tmp_path: Path) -> None:
    """Malformed JSON payloads should return deterministic validation errors."""
    runtime = _runtime(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.patch(
        "/api/config",
        content="{not-json",
        headers={**_headers(runtime), "content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_patch_config_rejects_unknown_top_level_field(tmp_path: Path) -> None:
    """Unknown top-level payload fields should be rejected."""
    runtime = _runtime(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.patch(
        "/api/config",
        json={"unknown": {"value": True}},
        headers=_headers(runtime),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_patch_config_rejects_non_boolean_heartbeat_enabled(tmp_path: Path) -> None:
    """heartbeat.enabled must be boolean."""
    runtime = _runtime(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.patch(
        "/api/config",
        json={"heartbeat": {"enabled": "yes"}},
        headers=_headers(runtime),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_post_restart_intent_acknowledges_and_records_timestamp(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    client = TestClient(build_dashboard_app(runtime))

    response = client.post("/api/config/restart-intent", headers=_headers(runtime))

    assert response.status_code == 200
    assert response.json()["acknowledged"] is True
    assert runtime.restart_requested_at is not None
