"""Tests for shared cron operation helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from squidbot.core.cron_ops import (
    add_job,
    format_jobs,
    generate_job_id,
    remove_job,
    set_enabled,
    validate_job,
)
from squidbot.core.models import CronJob


def _job(**overrides: object) -> CronJob:
    params: dict[str, object] = {
        "id": "abc12345",
        "name": "Morning ping",
        "message": "Good morning",
        "schedule": "0 9 * * *",
        "channel": "email:user@example.com",
        "enabled": True,
        "timezone": "local",
        "metadata": {"email_subject": "[squidbot] Morning ping"},
    }
    params.update(overrides)
    return CronJob(**params)


def test_generate_job_id_returns_eight_hex_chars() -> None:
    job_id = generate_job_id()
    assert len(job_id) == 8
    int(job_id, 16)


def test_validate_job_returns_none_for_valid_schedule() -> None:
    now = datetime(2026, 2, 27, 9, 0, tzinfo=UTC)
    assert validate_job(_job(), now=now) is None


def test_validate_job_returns_error_for_invalid_schedule() -> None:
    now = datetime(2026, 2, 27, 9, 0, tzinfo=UTC)
    error = validate_job(_job(schedule="not a schedule"), now=now)
    assert error is not None
    assert "Invalid schedule" in error


def test_add_job_appends_valid_job() -> None:
    existing = [_job(id="existing")]
    new_job = _job(id="new", schedule="every 60")
    updated = add_job(existing, new_job)
    assert [job.id for job in updated] == ["existing", "new"]


def test_add_job_raises_for_invalid_job() -> None:
    with pytest.raises(ValueError, match="Invalid schedule"):
        add_job([], _job(schedule="bad"))


def test_remove_job_returns_updated_list_and_found_flag() -> None:
    jobs = [_job(id="a"), _job(id="b")]
    updated, removed = remove_job(jobs, "a")
    assert removed is True
    assert [job.id for job in updated] == ["b"]


def test_set_enabled_updates_target_job_only() -> None:
    jobs = [_job(id="a", enabled=True), _job(id="b", enabled=True)]
    updated, found = set_enabled(jobs, "b", False)
    assert found is True
    assert updated[0].enabled is True
    assert updated[1].enabled is False


def test_format_jobs_matches_cli_layout() -> None:
    rendered = format_jobs([_job(id="id123")])
    assert "[on] id123  Morning ping" in rendered
    assert "schedule: 0 9 * * *  timezone: local  channel: email:user@example.com" in rendered
    assert "message:  Good morning" in rendered


def test_format_jobs_empty_message() -> None:
    assert format_jobs([]) == "No cron jobs configured."
