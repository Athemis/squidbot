"""Tests for the cron CLI commands (list_jobs, add, remove)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from _pytest.capture import CaptureFixture

from squidbot.cli.cron import add, list_jobs, remove
from squidbot.core.models import CronJob


def _job(**overrides: object) -> CronJob:
    """Create a test CronJob with sensible defaults."""
    params: dict[str, object] = {
        "id": "abc12345",
        "name": "Morning ping",
        "message": "Good morning",
        "schedule": "0 9 * * *",
        "channel": "cli:local",
        "enabled": True,
        "timezone": "local",
        "metadata": {},
    }
    params.update(overrides)
    return CronJob(**params)  # type: ignore[arg-type]


# ── list_jobs ──────────────────────────────────────────────────────────────


def test_list_jobs_prints_no_jobs_when_file_absent(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """list_jobs() prints 'No cron jobs configured.' when jobs file absent."""
    with patch("squidbot.cli.cron.Path.home", return_value=tmp_path):
        list_jobs()

    captured = capsys.readouterr()
    assert "No cron jobs configured." in captured.out


def test_list_jobs_prints_jobs_when_file_exists(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """list_jobs() prints formatted jobs when jobs file exists."""
    # Create jobs file
    cron_dir = tmp_path / ".squidbot" / "cron"
    cron_dir.mkdir(parents=True)
    jobs_file = cron_dir / "jobs.json"

    job1 = _job(id="job1", name="Morning", schedule="0 9 * * *")
    job2 = _job(id="job2", name="Evening", schedule="0 18 * * *", enabled=False)

    jobs_data = [
        {
            "id": job1.id,
            "name": job1.name,
            "message": job1.message,
            "schedule": job1.schedule,
            "channel": job1.channel,
            "enabled": job1.enabled,
            "timezone": job1.timezone,
            "last_run": None,
            "metadata": {},
        },
        {
            "id": job2.id,
            "name": job2.name,
            "message": job2.message,
            "schedule": job2.schedule,
            "channel": job2.channel,
            "enabled": job2.enabled,
            "timezone": job2.timezone,
            "last_run": None,
            "metadata": {},
        },
    ]
    jobs_file.write_text(json.dumps(jobs_data, indent=2))

    with patch("squidbot.cli.cron.Path.home", return_value=tmp_path):
        list_jobs()

    captured = capsys.readouterr()
    assert "job1" in captured.out
    assert "Morning" in captured.out
    assert "[on]" in captured.out
    assert "job2" in captured.out
    assert "Evening" in captured.out
    assert "[off]" in captured.out


# ── add ────────────────────────────────────────────────────────────────────


def test_add_with_valid_schedule_prints_success_and_persists(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """add() with valid schedule prints success message and persists job."""
    cron_dir = tmp_path / ".squidbot" / "cron"
    cron_dir.mkdir(parents=True)

    with (
        patch("squidbot.cli.cron.Path.home", return_value=tmp_path),
        patch("squidbot.core.cron_ops.generate_job_id", return_value="test1234"),
    ):
        add(
            name="Test Job",
            message="Test message",
            schedule="0 9 * * *",
            channel="cli:local",
        )

    captured = capsys.readouterr()
    assert "Added cron job 'Test Job'" in captured.out
    assert "test1234" in captured.out

    # Verify persistence
    jobs_file = cron_dir / "jobs.json"
    assert jobs_file.exists()
    data = json.loads(jobs_file.read_text())
    assert len(data) == 1
    assert data[0]["id"] == "test1234"
    assert data[0]["name"] == "Test Job"
    assert data[0]["message"] == "Test message"
    assert data[0]["schedule"] == "0 9 * * *"


def test_add_with_invalid_schedule_prints_error_and_exits(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """add() with invalid schedule prints error and raises SystemExit(2)."""
    cron_dir = tmp_path / ".squidbot" / "cron"
    cron_dir.mkdir(parents=True)

    with (
        patch("squidbot.cli.cron.Path.home", return_value=tmp_path),
        patch("squidbot.core.cron_ops.generate_job_id", return_value="test1234"),
        pytest.raises(SystemExit) as exc_info,
    ):
        add(
            name="Bad Job",
            message="Test message",
            schedule="not a valid schedule",
            channel="cli:local",
        )

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "Error:" in captured.out
    assert "Invalid schedule" in captured.out


def test_add_appends_to_existing_jobs(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """add() appends new job to existing jobs list."""
    cron_dir = tmp_path / ".squidbot" / "cron"
    cron_dir.mkdir(parents=True)
    jobs_file = cron_dir / "jobs.json"

    # Create initial job
    initial_job = {
        "id": "existing",
        "name": "Existing",
        "message": "Existing message",
        "schedule": "0 9 * * *",
        "channel": "cli:local",
        "enabled": True,
        "timezone": "local",
        "last_run": None,
        "metadata": {},
    }
    jobs_file.write_text(json.dumps([initial_job], indent=2))

    with (
        patch("squidbot.cli.cron.Path.home", return_value=tmp_path),
        patch("squidbot.core.cron_ops.generate_job_id", return_value="new1234"),
    ):
        add(
            name="New Job",
            message="New message",
            schedule="0 18 * * *",
            channel="cli:local",
        )

    # Verify both jobs exist
    data = json.loads(jobs_file.read_text())
    assert len(data) == 2
    assert data[0]["id"] == "existing"
    assert data[1]["id"] == "new1234"


def test_add_uses_default_channel(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """add() uses 'cli:local' as default channel."""
    cron_dir = tmp_path / ".squidbot" / "cron"
    cron_dir.mkdir(parents=True)

    with (
        patch("squidbot.cli.cron.Path.home", return_value=tmp_path),
        patch("squidbot.core.cron_ops.generate_job_id", return_value="test1234"),
    ):
        add(
            name="Test Job",
            message="Test message",
            schedule="0 9 * * *",
        )

    jobs_file = cron_dir / "jobs.json"
    data = json.loads(jobs_file.read_text())
    assert data[0]["channel"] == "cli:local"


# ── remove ─────────────────────────────────────────────────────────────────


def test_remove_with_existing_job_prints_success_and_persists(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """remove() with existing job prints success and removes from file."""
    cron_dir = tmp_path / ".squidbot" / "cron"
    cron_dir.mkdir(parents=True)
    jobs_file = cron_dir / "jobs.json"

    # Create initial jobs
    jobs_data = [
        {
            "id": "job1",
            "name": "Job 1",
            "message": "Message 1",
            "schedule": "0 9 * * *",
            "channel": "cli:local",
            "enabled": True,
            "timezone": "local",
            "last_run": None,
            "metadata": {},
        },
        {
            "id": "job2",
            "name": "Job 2",
            "message": "Message 2",
            "schedule": "0 18 * * *",
            "channel": "cli:local",
            "enabled": True,
            "timezone": "local",
            "last_run": None,
            "metadata": {},
        },
    ]
    jobs_file.write_text(json.dumps(jobs_data, indent=2))

    with patch("squidbot.cli.cron.Path.home", return_value=tmp_path):
        remove("job1")

    captured = capsys.readouterr()
    assert "Removed job 'job1'" in captured.out

    # Verify job1 is removed
    data = json.loads(jobs_file.read_text())
    assert len(data) == 1
    assert data[0]["id"] == "job2"


def test_remove_with_missing_job_prints_not_found(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """remove() with missing job prints 'No job found ...' and does not modify file."""
    cron_dir = tmp_path / ".squidbot" / "cron"
    cron_dir.mkdir(parents=True)
    jobs_file = cron_dir / "jobs.json"

    # Create initial job
    jobs_data = [
        {
            "id": "job1",
            "name": "Job 1",
            "message": "Message 1",
            "schedule": "0 9 * * *",
            "channel": "cli:local",
            "enabled": True,
            "timezone": "local",
            "last_run": None,
            "metadata": {},
        },
    ]
    jobs_file.write_text(json.dumps(jobs_data, indent=2))

    with patch("squidbot.cli.cron.Path.home", return_value=tmp_path):
        remove("nonexistent")

    captured = capsys.readouterr()
    assert "No job found with id 'nonexistent'" in captured.out

    # Verify file unchanged
    data = json.loads(jobs_file.read_text())
    assert len(data) == 1
    assert data[0]["id"] == "job1"


def test_remove_when_jobs_file_absent_prints_not_found(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """remove() when jobs file absent prints 'No job found ...'."""
    with patch("squidbot.cli.cron.Path.home", return_value=tmp_path):
        remove("nonexistent")

    captured = capsys.readouterr()
    assert "No job found with id 'nonexistent'" in captured.out


def test_remove_last_job_deletes_file(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """remove() leaves empty jobs list when last job is deleted."""
    cron_dir = tmp_path / ".squidbot" / "cron"
    cron_dir.mkdir(parents=True)
    jobs_file = cron_dir / "jobs.json"

    # Create single job
    jobs_data = [
        {
            "id": "job1",
            "name": "Job 1",
            "message": "Message 1",
            "schedule": "0 9 * * *",
            "channel": "cli:local",
            "enabled": True,
            "timezone": "local",
            "last_run": None,
            "metadata": {},
        },
    ]
    jobs_file.write_text(json.dumps(jobs_data, indent=2))

    with patch("squidbot.cli.cron.Path.home", return_value=tmp_path):
        remove("job1")

    captured = capsys.readouterr()
    assert "Removed job 'job1'" in captured.out

    # Verify file now contains empty list
    data = json.loads(jobs_file.read_text())
    assert len(data) == 0
