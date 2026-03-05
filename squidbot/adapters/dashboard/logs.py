"""Bounded log buffer for dashboard log-tail APIs.

The buffer keeps a fixed number of most-recent entries and exposes cursor-based
paging for "load older" behavior in the web dashboard.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock


@dataclass(frozen=True)
class DashboardLogEntry:
    """Single structured log entry stored in the dashboard buffer."""

    cursor: int
    ts: datetime
    level: str
    message: str


@dataclass(frozen=True)
class DashboardLogPage:
    """Page response for dashboard log pagination."""

    entries: list[DashboardLogEntry]
    next_before_cursor: int | None


class DashboardLogBuffer:
    """Thread-safe bounded log buffer with cursor pagination."""

    def __init__(self, max_entries: int = 2_000) -> None:
        """Initialize the buffer.

        Args:
            max_entries: Maximum number of entries retained in memory.
        """
        if max_entries <= 0:
            raise ValueError("max_entries must be greater than zero")
        self._max_entries = max_entries
        self._entries: deque[DashboardLogEntry] = deque(maxlen=max_entries)
        self._next_cursor = 0
        self._lock = Lock()

    def append(self, *, level: str, message: str) -> None:
        """Append a new log entry to the bounded buffer.

        Args:
            level: Log severity level.
            message: Log text content.
        """
        with self._lock:
            entry = DashboardLogEntry(
                cursor=self._next_cursor,
                ts=datetime.now(UTC),
                level=level,
                message=message,
            )
            self._entries.append(entry)
            self._next_cursor += 1

    def page(self, *, limit: int, before_cursor: int | None = None) -> DashboardLogPage:
        """Return one page of log entries.

        Args:
            limit: Maximum number of entries to return.
            before_cursor: Exclusive upper-bound cursor for older pagination.
                The returned next_before_cursor equals the oldest cursor in the
                current page when older entries remain.

        Returns:
            A page containing entries ordered oldest-to-newest.
        """
        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        with self._lock:
            entries = list(self._entries)

        if before_cursor is not None:
            entries = [entry for entry in entries if entry.cursor < before_cursor]

        if not entries:
            return DashboardLogPage(entries=[], next_before_cursor=None)

        page_entries = entries[-limit:]
        oldest_cursor = page_entries[0].cursor
        has_older = any(entry.cursor < oldest_cursor for entry in entries)
        next_before_cursor = oldest_cursor if has_older else None
        return DashboardLogPage(entries=page_entries, next_before_cursor=next_before_cursor)
