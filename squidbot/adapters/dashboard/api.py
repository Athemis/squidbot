"""FastAPI application factory for the dashboard adapter.

This module hosts dashboard HTTP endpoints and shared request guards for
localhost-only mutating operations.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from starlette.responses import StreamingResponse
from starlette.staticfiles import StaticFiles

from squidbot.adapters.dashboard.chat import StreamingDashboardChannel, start_ndjson_stream
from squidbot.adapters.dashboard.logs import DashboardLogBuffer
from squidbot.adapters.dashboard.runtime import DashboardRuntime
from squidbot.config.schema import Settings
from squidbot.core.models import GatewayState, Session


def _error_response(code: str, message: str, status_code: int) -> JSONResponse:
    """Build a consistent JSON error response payload."""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _extract_host_name(host_header: str | None) -> str | None:
    """Extract host name from Host header value, stripping optional port."""
    if not host_header:
        return None
    cleaned = host_header.strip()
    if not cleaned:
        return None
    if cleaned.startswith("["):
        end = cleaned.find("]")
        if end == -1:
            return None
        host = cleaned[1:end]
        return host.lower() if host else None
    return cleaned.split(":", 1)[0].lower() or None


def _is_loopback_host(host: str | None) -> bool:
    """Return True when host is localhost or a loopback IP literal."""
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_loopback_origin(origin: str) -> bool:
    """Return True when Origin header points to a loopback host."""
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = parsed.hostname
    return _is_loopback_host(hostname)


def require_local_write(request: Request, runtime: DashboardRuntime) -> JSONResponse | None:
    """Validate local-write guard conditions for mutating dashboard requests.

    Args:
        request: Incoming HTTP request.
        runtime: Dashboard runtime holding the active local nonce.

    Returns:
        None when the request is allowed, otherwise a JSONResponse explaining
        why the request was rejected.
    """
    blocked = require_local_context(request)
    if blocked is not None:
        return blocked

    nonce = request.headers.get("x-squidbot-local-nonce")
    if nonce is None or not nonce:
        return _error_response("MISSING_NONCE", "Missing X-Squidbot-Local-Nonce", status_code=403)
    if nonce != runtime.local_nonce:
        return _error_response("INVALID_NONCE", "Invalid X-Squidbot-Local-Nonce", status_code=403)
    return None


def require_local_context(request: Request) -> JSONResponse | None:
    """Validate loopback host/origin context for local dashboard requests."""
    host = _extract_host_name(request.headers.get("host"))
    if not _is_loopback_host(host):
        return _error_response("INVALID_HOST", "Host must be loopback-only", status_code=403)

    origin = request.headers.get("origin")
    if origin is not None and not _is_loopback_origin(origin):
        return _error_response("INVALID_ORIGIN", "Origin must be loopback-only", status_code=403)
    return None


def _default_runtime() -> DashboardRuntime:
    """Create a fallback runtime used by import-level app factory tests."""
    return DashboardRuntime(
        state=GatewayState(
            active_sessions={},
            channel_status=[],
            cron_jobs_cache=[],
            started_at=datetime.now(),
        ),
        log_buffer=DashboardLogBuffer(),
        config_path=None,
    )


def _default_static_dir() -> Path:
    """Return package-owned static asset directory path."""
    return Path(__file__).with_name("static")


def _config_error_response() -> JSONResponse:
    """Return a consistent error when config endpoints are unavailable."""
    return _error_response(
        "CONFIG_UNAVAILABLE",
        "Dashboard config endpoints require a configured config_path",
        status_code=500,
    )


def _load_runtime_settings(runtime: DashboardRuntime) -> Settings | None:
    """Load settings for config APIs when config_path is available."""
    if runtime.config_path is None:
        return None
    return Settings.load(runtime.config_path)


def _validate_config_patch(payload: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Validate incoming config patch payload and return normalized data."""
    if not isinstance(payload, dict):
        return None, "payload must be an object"

    allowed_top = {"channels", "heartbeat"}
    top_keys = set(payload.keys())
    unknown_top = top_keys - allowed_top
    if unknown_top:
        unknown = sorted(unknown_top)[0]
        return None, f"unknown top-level field: {unknown}"

    normalized: dict[str, Any] = {}
    if "channels" in payload:
        channels = payload["channels"]
        if not isinstance(channels, dict):
            return None, "channels must be an object"
        allowed_channels = {"matrix_enabled", "email_enabled"}
        unknown_channels = set(channels.keys()) - allowed_channels
        if unknown_channels:
            unknown = sorted(unknown_channels)[0]
            return None, f"unknown channels field: {unknown}"
        for key, value in channels.items():
            if not isinstance(value, bool):
                return None, f"{key} must be a boolean"
        normalized["channels"] = channels

    if "heartbeat" in payload:
        heartbeat = payload["heartbeat"]
        if not isinstance(heartbeat, dict):
            return None, "heartbeat must be an object"
        allowed_heartbeat = {"enabled", "interval_minutes"}
        unknown_heartbeat = set(heartbeat.keys()) - allowed_heartbeat
        if unknown_heartbeat:
            unknown = sorted(unknown_heartbeat)[0]
            return None, f"unknown heartbeat field: {unknown}"
        if "enabled" in heartbeat and not isinstance(heartbeat["enabled"], bool):
            return None, "enabled must be a boolean"
        if "interval_minutes" in heartbeat:
            interval = heartbeat["interval_minutes"]
            if type(interval) is not int or interval <= 0:
                return None, "interval_minutes must be a positive integer"
        normalized["heartbeat"] = heartbeat

    return normalized, None


def build_dashboard_app(
    runtime: DashboardRuntime | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """Create the dashboard FastAPI application instance.

    Args:
        runtime: Optional runtime dependency container.

    Returns:
        A FastAPI application configured for the squidbot dashboard API.
    """
    app = FastAPI(title="squidbot dashboard", docs_url=None, redoc_url=None)
    active_runtime = runtime or _default_runtime()
    frontend_static_dir = static_dir or _default_static_dir()

    assets_dir = frontend_static_dir / "assets"
    if frontend_static_dir.exists() and (frontend_static_dir / "index.html").exists():
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="dashboard-assets")

        @app.get("/")
        async def dashboard_index() -> FileResponse:
            """Serve packaged dashboard frontend entrypoint."""
            return FileResponse(frontend_static_dir / "index.html")

    else:

        @app.get("/")
        async def dashboard_index_missing_assets() -> JSONResponse:
            """Return deterministic error when packaged frontend is unavailable."""
            return _error_response(
                "DASHBOARD_ASSETS_MISSING",
                "Packaged dashboard static assets are missing",
                status_code=503,
            )

    @app.get("/api/bootstrap")
    async def bootstrap(request: Request) -> JSONResponse:
        """Expose dashboard bootstrap metadata for local clients."""
        blocked = require_local_context(request)
        if blocked is not None:
            return blocked
        return JSONResponse(status_code=200, content={"local_nonce": active_runtime.local_nonce})

    @app.get("/api/overview")
    async def overview(request: Request) -> JSONResponse:
        """Return high-level runtime overview for the dashboard."""
        blocked = require_local_context(request)
        if blocked is not None:
            return blocked

        channels = [
            {
                "name": item.name,
                "enabled": item.enabled,
                "connected": item.connected,
                "error": item.error,
            }
            for item in active_runtime.state.channel_status
        ]
        sessions = [
            {
                "session_id": item.session_id,
                "channel": item.channel,
                "sender_id": item.sender_id,
                "started_at": item.started_at.isoformat(),
                "message_count": item.message_count,
            }
            for item in active_runtime.state.active_sessions.values()
        ]
        return JSONResponse(
            status_code=200,
            content={
                "started_at": active_runtime.state.started_at.isoformat(),
                "channels": channels,
                "active_sessions": sessions,
                "cron_jobs": len(active_runtime.state.cron_jobs_cache),
            },
        )

    @app.get("/api/logs")
    async def logs(request: Request, limit: int = 200, before: int | None = None) -> JSONResponse:
        """Return paginated log entries from the dashboard buffer."""
        blocked = require_local_context(request)
        if blocked is not None:
            return blocked
        try:
            page = active_runtime.log_buffer.page(limit=limit, before_cursor=before)
        except ValueError as exc:
            return _error_response("VALIDATION_ERROR", str(exc), status_code=400)

        entries = [
            {
                "cursor": entry.cursor,
                "ts": entry.ts.isoformat(),
                "level": entry.level,
                "message": entry.message,
            }
            for entry in page.entries
        ]
        return JSONResponse(
            status_code=200,
            content={"entries": entries, "next_before_cursor": page.next_before_cursor},
        )

    @app.get("/api/config")
    async def read_config(request: Request) -> JSONResponse:
        """Return a restricted editable projection of runtime config."""
        blocked = require_local_context(request)
        if blocked is not None:
            return blocked
        settings = _load_runtime_settings(active_runtime)
        if settings is None:
            return _config_error_response()

        return JSONResponse(
            status_code=200,
            content={
                "channels": {
                    "matrix_enabled": settings.channels.matrix.enabled,
                    "email_enabled": settings.channels.email.enabled,
                },
                "heartbeat": {
                    "enabled": settings.agents.heartbeat.enabled,
                    "interval_minutes": settings.agents.heartbeat.interval_minutes,
                },
            },
        )

    @app.patch("/api/config")
    async def patch_config(request: Request) -> JSONResponse:
        """Placeholder config patch endpoint guarded by local-write checks."""
        blocked = require_local_write(request, active_runtime)
        if blocked is not None:
            return blocked

        settings = _load_runtime_settings(active_runtime)
        if settings is None:
            return _config_error_response()

        try:
            payload = await request.json()
        except ValueError, json.JSONDecodeError:
            return _error_response(
                "VALIDATION_ERROR",
                "payload must be valid JSON",
                status_code=400,
            )
        patch_data, error = _validate_config_patch(payload)
        if error is not None:
            return _error_response("VALIDATION_ERROR", error, status_code=400)

        changed = False
        channels = patch_data.get("channels", {}) if patch_data is not None else {}
        heartbeat = patch_data.get("heartbeat", {}) if patch_data is not None else {}

        if (
            "matrix_enabled" in channels
            and settings.channels.matrix.enabled != channels["matrix_enabled"]
        ):
            settings.channels.matrix.enabled = channels["matrix_enabled"]
            changed = True
        if (
            "email_enabled" in channels
            and settings.channels.email.enabled != channels["email_enabled"]
        ):
            settings.channels.email.enabled = channels["email_enabled"]
            changed = True
        if "enabled" in heartbeat and settings.agents.heartbeat.enabled != heartbeat["enabled"]:
            settings.agents.heartbeat.enabled = heartbeat["enabled"]
            changed = True
        if (
            "interval_minutes" in heartbeat
            and settings.agents.heartbeat.interval_minutes != heartbeat["interval_minutes"]
        ):
            settings.agents.heartbeat.interval_minutes = heartbeat["interval_minutes"]
            changed = True

        config_path = active_runtime.config_path
        if config_path is None:
            return _config_error_response()
        if changed:
            settings.save(config_path)
        return JSONResponse(
            status_code=200,
            content={"saved": True, "restart_required": changed},
        )

    @app.post("/api/config/restart-intent")
    async def restart_intent(request: Request) -> JSONResponse:
        """Record explicit operator intent to restart the gateway process."""
        blocked = require_local_write(request, active_runtime)
        if blocked is not None:
            return blocked
        active_runtime.mark_restart_requested()
        timestamp = (
            active_runtime.restart_requested_at.isoformat()
            if active_runtime.restart_requested_at is not None
            else None
        )
        return JSONResponse(
            status_code=200, content={"acknowledged": True, "requested_at": timestamp}
        )

    @app.post("/api/chat/stream")
    async def chat_stream(request: Request) -> Any:
        """Stream operator chat responses as NDJSON frames."""
        blocked = require_local_write(request, active_runtime)
        if blocked is not None:
            return blocked

        agent_loop = active_runtime.agent_loop
        if agent_loop is None:
            return _error_response(
                "CHAT_UNAVAILABLE", "agent loop is not configured", status_code=503
            )

        try:
            payload = await request.json()
        except ValueError, json.JSONDecodeError:
            return _error_response(
                "VALIDATION_ERROR", "payload must be valid JSON", status_code=400
            )
        if not isinstance(payload, dict):
            return _error_response("VALIDATION_ERROR", "payload must be an object", status_code=400)

        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return _error_response("VALIDATION_ERROR", "prompt is required", status_code=400)

        session = Session(channel="dashboard", sender_id="local")

        async def _producer(frame_queue: asyncio.Queue[str | None]) -> None:
            stream_channel = StreamingDashboardChannel(frame_queue)
            try:
                await agent_loop.run(session, prompt, stream_channel)
            except Exception as exc:  # noqa: BLE001
                logger.warning("dashboard.chat: stream producer failed: {}", exc)
                frame = json.dumps({"type": "error", "message": "internal error"})
                await frame_queue.put(f"{frame}\n")

        return StreamingResponse(start_ndjson_stream(_producer), media_type="application/x-ndjson")

    return app
