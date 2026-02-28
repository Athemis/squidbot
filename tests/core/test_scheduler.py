"""Tests for the cron scheduler."""

from __future__ import annotations

from datetime import UTC, datetime

from squidbot.core.models import CronJob
from squidbot.core.scheduler import is_due, parse_schedule


def test_parse_cron_expression():
    job = CronJob(id="1", name="test", message="hi", schedule="0 9 * * *", channel="cli:local")
    next_run = parse_schedule(job, now=datetime(2026, 2, 21, 8, 0, tzinfo=UTC))
    assert next_run is not None
    assert next_run.hour == 9


def test_parse_interval():
    job = CronJob(id="1", name="test", message="hi", schedule="every 60", channel="cli:local")
    next_run = parse_schedule(job, now=datetime(2026, 2, 21, 8, 0, tzinfo=UTC))
    assert next_run is not None


def test_parse_interval_zero_is_invalid() -> None:
    job = CronJob(id="1", name="test", message="hi", schedule="every 0", channel="cli:local")
    next_run = parse_schedule(job, now=datetime(2026, 2, 21, 8, 0, tzinfo=UTC))
    assert next_run is None


def test_parse_interval_negative_is_invalid() -> None:
    job = CronJob(id="1", name="test", message="hi", schedule="every -1", channel="cli:local")
    next_run = parse_schedule(job, now=datetime(2026, 2, 21, 8, 0, tzinfo=UTC))
    assert next_run is None


def test_parse_interval_one_second_is_valid() -> None:
    job = CronJob(id="1", name="test", message="hi", schedule="every 1", channel="cli:local")
    next_run = parse_schedule(job, now=datetime(2026, 2, 21, 8, 0, tzinfo=UTC))
    assert next_run is not None


def test_is_due_past_time():
    job = CronJob(
        id="1",
        name="test",
        message="hi",
        schedule="0 9 * * *",
        channel="cli:local",
        last_run=datetime(2026, 2, 21, 8, 0, tzinfo=UTC),
    )
    now = datetime(2026, 2, 21, 9, 1, tzinfo=UTC)
    assert is_due(job, now=now)


def test_is_not_due_before_time():
    job = CronJob(id="1", name="test", message="hi", schedule="0 9 * * *", channel="cli:local")
    now = datetime(2026, 2, 21, 8, 59, tzinfo=UTC)
    assert not is_due(job, now=now)


def test_is_not_due_for_zero_interval() -> None:
    now = datetime(2026, 2, 21, 8, 59, tzinfo=UTC)
    job = CronJob(
        id="1",
        name="test",
        message="hi",
        schedule="every 0",
        channel="cli:local",
        last_run=now,
    )
    assert not is_due(job, now=now)


def test_is_not_due_for_negative_interval() -> None:
    now = datetime(2026, 2, 21, 8, 59, tzinfo=UTC)
    job = CronJob(
        id="1",
        name="test",
        message="hi",
        schedule="every -1",
        channel="cli:local",
        last_run=now,
    )
    assert not is_due(job, now=now)


def test_is_due_for_fixed_offset_timezone():
    job = CronJob(
        id="1",
        name="test",
        message="hi",
        schedule="0 9 * * *",
        channel="cli:local",
        timezone="+01:00",
    )

    assert not is_due(job, now=datetime(2026, 2, 21, 7, 59, tzinfo=UTC))
    assert is_due(job, now=datetime(2026, 2, 21, 8, 0, tzinfo=UTC))
