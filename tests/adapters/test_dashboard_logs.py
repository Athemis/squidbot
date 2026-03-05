"""Tests for dashboard log buffering and pagination behavior.

This module validates bounded retention, cursor pagination, and eviction
semantics of `DashboardLogBuffer`. It protects dashboard log-tail reliability
without unbounded memory growth.
"""

from __future__ import annotations

import pytest

from squidbot.adapters.dashboard.logs import DashboardLogBuffer


def test_log_buffer_returns_newest_slice_and_cursor() -> None:
    """The first page should include the newest entries and a cursor."""
    log_buffer = DashboardLogBuffer(max_entries=5)
    for index in range(5):
        log_buffer.append(level="INFO", message=f"line-{index}")

    page = log_buffer.page(limit=2)

    assert [entry.message for entry in page.entries] == ["line-3", "line-4"]
    assert page.next_before_cursor is not None


def test_log_buffer_loads_older_entries_from_cursor() -> None:
    """The before cursor should return older entries."""
    log_buffer = DashboardLogBuffer(max_entries=6)
    for index in range(6):
        log_buffer.append(level="INFO", message=f"line-{index}")

    first_page = log_buffer.page(limit=2)
    second_page = log_buffer.page(limit=2, before_cursor=first_page.next_before_cursor)

    assert [entry.message for entry in second_page.entries] == ["line-2", "line-3"]


def test_log_buffer_pagination_is_contiguous_without_duplicates() -> None:
    """Walking pages should return every retained entry exactly once."""
    log_buffer = DashboardLogBuffer(max_entries=6)
    for index in range(6):
        log_buffer.append(level="INFO", message=f"line-{index}")

    cursor: int | None = None
    collected: list[str] = []
    while True:
        page = log_buffer.page(limit=2, before_cursor=cursor)
        if not page.entries:
            break
        collected.extend(entry.message for entry in page.entries)
        if page.next_before_cursor is None:
            break
        cursor = page.next_before_cursor

    assert collected == ["line-4", "line-5", "line-2", "line-3", "line-0", "line-1"]


def test_log_buffer_drops_oldest_when_full() -> None:
    """Buffer capacity should evict oldest messages first."""
    log_buffer = DashboardLogBuffer(max_entries=3)
    for index in range(5):
        log_buffer.append(level="INFO", message=f"line-{index}")

    page = log_buffer.page(limit=10)

    assert [entry.message for entry in page.entries] == ["line-2", "line-3", "line-4"]


def test_log_buffer_rejects_non_positive_limits() -> None:
    """Constructor and page guard clauses reject invalid limits."""
    with pytest.raises(ValueError):
        DashboardLogBuffer(max_entries=0)

    log_buffer = DashboardLogBuffer(max_entries=3)
    with pytest.raises(ValueError):
        log_buffer.page(limit=0)


def test_log_buffer_returns_empty_page_when_before_cursor_excludes_all() -> None:
    """A before cursor older than any entry should return an empty page."""
    log_buffer = DashboardLogBuffer(max_entries=3)
    for index in range(3):
        log_buffer.append(level="INFO", message=f"line-{index}")

    page = log_buffer.page(limit=3, before_cursor=0)

    assert page.entries == []
    assert page.next_before_cursor is None
