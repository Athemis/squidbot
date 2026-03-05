"""Import-level tests for dashboard adapter modules."""

from __future__ import annotations

from fastapi import FastAPI


def test_build_dashboard_app_configuration() -> None:
    """The dashboard API module exposes a configured FastAPI app factory."""
    from squidbot.adapters.dashboard.api import build_dashboard_app

    app = build_dashboard_app()

    assert isinstance(app, FastAPI)
    assert app.title == "squidbot dashboard"
    assert app.docs_url is None
    assert app.redoc_url is None
