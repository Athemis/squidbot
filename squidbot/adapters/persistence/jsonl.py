"""Filesystem persistence for squidbot memory.

This adapter persists global conversation history as JSONL (one Message per line), the
global cross-session memory document as Markdown, and cron jobs as JSON.

Design goals:
- Keep the agent responsive: all filesystem IO is run in ``asyncio.to_thread``.
- Be resilient: malformed/partial JSONL lines are skipped instead of crashing.
- Avoid corruption: whole-file writes (MEMORY.md, cron/jobs.json) are written atomically.
- Support concurrent access: history.jsonl appends use ``fcntl.flock``.

Directory layout:
    <base_dir>/
    ├── history.jsonl          # all channels, append-only
    ├── workspace/
    │   └── MEMORY.md          # global cross-session memory
    └── cron/
        └── jobs.json          # scheduled task list
"""

from __future__ import annotations

import asyncio
import collections
import fcntl
import itertools
import json
import os
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from squidbot.core.models import CronJob, Message, ToolCall


def _serialize_message(message: Message) -> str:
    """Serialize a Message to a JSONL line.

    Args:
        message: Message to serialize.

    Returns:
        A single JSON object encoded as a string (no trailing newline).
    """
    d: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
        "timestamp": message.timestamp.isoformat(),
    }
    if message.tool_calls:
        d["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in message.tool_calls
        ]
    if message.tool_call_id:
        d["tool_call_id"] = message.tool_call_id
    if message.reasoning_content is not None:
        d["reasoning_content"] = message.reasoning_content
    if message.channel is not None:
        d["channel"] = message.channel
    if message.sender_id is not None:
        d["sender_id"] = message.sender_id
    return json.dumps(d, ensure_ascii=False)


def deserialize_message(line: str) -> Message:
    """Deserialize a JSONL line to a Message.

    Args:
        line: A single JSON object encoded as a string.

    Returns:
        The parsed Message.
    """
    d = json.loads(line)
    tool_calls = None
    if "tool_calls" in d:
        tool_calls = [
            ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
            for tc in d["tool_calls"]
        ]
    return Message(
        role=d["role"],
        content=d.get("content", ""),
        tool_calls=tool_calls,
        tool_call_id=d.get("tool_call_id"),
        reasoning_content=d.get("reasoning_content"),
        timestamp=datetime.fromisoformat(d["timestamp"]),
        channel=d.get("channel"),
        sender_id=d.get("sender_id"),
    )


def deserialize_message_safe(line: str) -> Message | None:
    """Best-effort JSONL message parser.

    This is used when scanning history.jsonl where lines may be partially written,
    corrupted, or from older versions. Failures are represented as ``None`` so the
    caller can skip the line and continue.

    Args:
        line: A single JSON object encoded as a string.

    Returns:
        A Message if parsing succeeds, otherwise ``None``.
    """
    try:
        return deserialize_message(line)
    except json.JSONDecodeError, KeyError, TypeError, ValueError:
        return None


def _history_file(base_dir: Path) -> Path:
    """Return the global history JSONL path.

    Note: Does not create directories. ``JsonlMemory.__init__`` creates all required
    directories at startup; callers outside of ``JsonlMemory`` must ensure the directory
    already exists (e.g. ``SearchHistoryTool`` always runs alongside a ``JsonlMemory``
    instance that shares the same ``base_dir``).
    """
    return base_dir / "history.jsonl"


def _global_memory_file(base_dir: Path) -> Path:
    """Return the global MEMORY.md path.

    Note: Does not create directories. ``JsonlMemory.__init__`` creates all required
    directories at startup; callers outside of ``JsonlMemory`` must ensure the directory
    already exists.
    """
    return base_dir / "workspace" / "MEMORY.md"


def _cron_file(base_dir: Path) -> Path:
    """Return the cron jobs JSON path.

    Note: Does not create directories. ``JsonlMemory.__init__`` creates all required
    directories at startup; callers outside of ``JsonlMemory`` must ensure the directory
    already exists.
    """
    return base_dir / "cron" / "jobs.json"


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text to a file atomically.

    We write to a temporary file in the same directory and then replace the target
    path via ``os.replace``. On POSIX filesystems this makes the final update appear
    atomically (readers either see the old file or the new file, never a truncated
    intermediate).

    Args:
        path: Target file path.
        content: Full file contents to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Create the temp file in the target directory so os.replace() is a same-filesystem
    # rename (required for atomicity).
    fd, temp_path_str = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            # Ensure file content is pushed to disk before replace. (We intentionally
            # do not fsync the directory: this is a lightweight local tool and we
            # prefer minimal IO over full crash-consistency semantics.)
            os.fsync(temp_file.fileno())

        # os.replace() is atomic on POSIX when source/target are on the same filesystem.
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


class JsonlMemory:
    """
    Filesystem-based memory adapter using JSONL for history and JSON for jobs.

    History is stored in a single global history.jsonl file shared across all
    channels. Concurrent writes are protected by fcntl.flock. Methods are async
    to satisfy the MemoryPort protocol.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir
        # Create full directory structure once at startup so no method needs to mkdir.
        self._base.mkdir(parents=True, exist_ok=True)
        (self._base / "workspace").mkdir(parents=True, exist_ok=True)
        (self._base / "cron").mkdir(parents=True, exist_ok=True)
        # In-memory cache of recent history entries.
        # Populated on first load_history call; maintained on append.
        self._history_cache: collections.deque[Message] = collections.deque()
        self._history_cache_size: int = 0  # largest last_n ever requested
        self._history_cache_loaded: bool = False  # True after at least one disk read
        # Guards cache population: prevents two concurrent callers from both
        # executing the expensive disk read when the cache is cold.
        self._history_load_lock: asyncio.Lock = asyncio.Lock()

    async def load_history(self, last_n: int | None = None) -> list[Message]:
        """Load messages from the global history JSONL file.

        Args:
            last_n: If provided, return only the last N messages. If None, return all.

        Returns:
            List of messages in chronological order.

        Note:
            Results are cached in memory after the first bounded (last_n is not None) read.
            Subsequent calls with last_n <= the largest previously requested value are served
            from cache without disk I/O. Unbounded reads (last_n=None) always read from disk.
        """
        # Treat <=0 as "no history". This is useful for callers that want to disable
        # history without branching. It also prevents accidentally loading the full
        # file via Python slicing semantics (e.g. all_messages[-0:] == all_messages).
        if last_n is not None and last_n <= 0:
            return []

        # Cache hit: cache has been loaded from disk and covers the requested window.
        # The deque may hold fewer than last_n entries when history itself is shorter
        # than last_n — that is still a valid hit; we return whatever the cache holds.
        if last_n is not None and self._history_cache_loaded and last_n <= self._history_cache_size:
            skip = max(0, len(self._history_cache) - last_n)
            return list(itertools.islice(self._history_cache, skip, None))

        # Unbounded reads are never cached — skip the lock entirely.
        if last_n is None:
            return await self._load_history_from_disk(None)

        # Serialize concurrent cold-cache loads: only one caller reads from disk,
        # subsequent callers check the cache again under the lock and return early.
        async with self._history_load_lock:
            # Re-check inside the lock — a concurrent caller may have populated the
            # cache while we were waiting.
            if self._history_cache_loaded and last_n <= self._history_cache_size:
                skip = max(0, len(self._history_cache) - last_n)
                return list(itertools.islice(self._history_cache, skip, None))

            return await self._load_history_from_disk(last_n)

    async def _load_history_from_disk(self, last_n: int | None) -> list[Message]:
        """Read history from disk and, for bounded reads, update the in-memory cache.

        Must be called while holding self._history_load_lock for bounded reads.
        Unbounded reads (last_n=None) are not cached and may bypass the lock.
        """
        path = _history_file(self._base)

        def _read() -> tuple[list[Message], int, str | None]:
            if not path.exists():
                return [], 0, None

            skipped_lines = 0
            first_skipped_preview: str | None = None

            if last_n is not None and last_n > 0:
                block_size = 64 * 1024
                reverse_chrono_messages: list[Message] = []

                with path.open("rb") as f:
                    has_lock = False
                    try:
                        try:
                            # Best-effort shared lock: reduces the chance we read a
                            # partially-written line while another process appends.
                            # If locking is unavailable, we still proceed safely by
                            # skipping malformed lines.
                            fcntl.flock(f, fcntl.LOCK_SH)
                            has_lock = True
                        except Exception:
                            has_lock = False

                        f.seek(0, os.SEEK_END)
                        position = f.tell()
                        carry = b""

                        while position > 0 and len(reverse_chrono_messages) < last_n:
                            read_size = min(block_size, position)
                            position -= read_size
                            f.seek(position)
                            block = f.read(read_size)

                            data = block + carry
                            lines = data.split(b"\n")

                            if position > 0:
                                carry = lines[0]
                                complete_lines = lines[1:]
                            else:
                                carry = b""
                                complete_lines = lines

                            for raw_line in reversed(complete_lines):
                                line = raw_line.decode("utf-8", errors="replace").strip()
                                if not line:
                                    continue

                                message = deserialize_message_safe(line)
                                if message is None:
                                    skipped_lines += 1
                                    if first_skipped_preview is None:
                                        # Keep a short preview for debugging. Note: this may
                                        # include user content; it is truncated and logged
                                        # only once per load_history() call.
                                        first_skipped_preview = line[:120]
                                    continue

                                reverse_chrono_messages.append(message)
                                if len(reverse_chrono_messages) >= last_n:
                                    break
                    finally:
                        if has_lock:
                            with suppress(OSError):
                                fcntl.flock(f, fcntl.LOCK_UN)

                reverse_chrono_messages.reverse()
                return reverse_chrono_messages, skipped_lines, first_skipped_preview

            all_messages: list[Message] = []
            with path.open("r", encoding="utf-8", errors="replace") as f:
                has_lock = False
                try:
                    try:
                        # Same best-effort shared lock rationale as the last_n>0 path.
                        fcntl.flock(f, fcntl.LOCK_SH)
                        has_lock = True
                    except Exception:
                        has_lock = False

                    for text_line in f:
                        line = text_line.strip()
                        if not line:
                            continue

                        message = deserialize_message_safe(line)
                        if message is None:
                            skipped_lines += 1
                            if first_skipped_preview is None:
                                first_skipped_preview = line[:120]
                            continue

                        all_messages.append(message)
                finally:
                    if has_lock:
                        with suppress(OSError):
                            fcntl.flock(f, fcntl.LOCK_UN)

            if last_n is None:
                return all_messages, skipped_lines, first_skipped_preview

            return all_messages[-last_n:], skipped_lines, first_skipped_preview

        # Offload file IO so channels/LLM streaming isn't blocked by filesystem reads.
        messages, skipped_lines, preview = await asyncio.to_thread(_read)
        if skipped_lines:
            logger.warning(
                "Skipped {} malformed history line(s) in {}. First error preview: {!r}",
                skipped_lines,
                path,
                preview,
            )

        # Populate cache after disk read
        if last_n is not None:
            self._history_cache_size = max(self._history_cache_size, last_n)
            self._history_cache = collections.deque(
                messages[-self._history_cache_size :],
                maxlen=self._history_cache_size,
            )
            self._history_cache_loaded = True

        return messages

    async def append_message(self, message: Message) -> None:
        """Append a single message to the global history JSONL file.

        Uses fcntl.flock for write locking to allow safe concurrent access.

        Args:
            message: The message to append.
        """
        path = _history_file(self._base)

        def _write() -> None:
            with path.open("a", encoding="utf-8") as f:
                # Exclusive lock prevents multiple writers interleaving JSON fragments
                # on the same line.
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.write(_serialize_message(message) + "\n")
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

        await asyncio.to_thread(_write)

        # Update cache AFTER successful write — never ahead of disk.
        # deque with maxlen trims automatically in O(1).
        if self._history_cache_size > 0:
            self._history_cache.append(message)

    async def append_messages(self, messages: list[Message]) -> None:
        """Append multiple messages to history in a single file open and lock.

        This is an adapter-level extension that is not part of ``MemoryPort``.
        Callers that want batch writes should check ``hasattr(storage, "append_messages")``
        and fall back to ``append_message`` for other adapters.

        Args:
            messages: Messages to append in order.
        """
        if not messages:
            return
        path = _history_file(self._base)
        # Serialize before entering the thread to keep the lock window minimal.
        lines = "\n".join(_serialize_message(m) for m in messages) + "\n"

        def _write() -> None:
            with open(path, "a", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.write(lines)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

        await asyncio.to_thread(_write)

        # Update cache AFTER successful write — never ahead of disk.
        # deque with maxlen trims automatically in O(1).
        if self._history_cache_size > 0:
            for message in messages:
                self._history_cache.append(message)

    async def load_global_memory(self) -> str:
        """Load the global cross-session memory document."""
        path = _global_memory_file(self._base)

        def _read() -> str:
            if not path.exists():
                return ""
            return path.read_text(encoding="utf-8")

        return await asyncio.to_thread(_read)

    async def save_global_memory(self, content: str) -> None:
        """Overwrite the global memory document."""
        path = _global_memory_file(self._base)
        await asyncio.to_thread(_atomic_write_text, path, content)

    async def load_cron_jobs(self) -> list[CronJob]:
        """Load all scheduled jobs from the JSON file."""
        path = _cron_file(self._base)

        def _read() -> list[CronJob]:
            if not path.exists():
                return []
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                jobs = []
                for d in data:
                    last_run = datetime.fromisoformat(d["last_run"]) if d.get("last_run") else None
                    metadata_raw = d.get("metadata", {})
                    metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
                    jobs.append(
                        CronJob(
                            id=d["id"],
                            name=d["name"],
                            message=d["message"],
                            schedule=d["schedule"],
                            channel=d.get("channel", "cli:local"),
                            enabled=d.get("enabled", True),
                            timezone=d.get("timezone", "local"),
                            last_run=last_run,
                            metadata=metadata,
                        )
                    )
            except json.JSONDecodeError, TypeError, ValueError, KeyError:
                logger.warning("Failed to load cron jobs from {}; returning empty list", path)
                return []

            return jobs

        return await asyncio.to_thread(_read)

    async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
        """Persist the full job list.

        Args:
            jobs: The complete list of cron jobs to write.
        """
        path = _cron_file(self._base)
        data = [
            {
                "id": j.id,
                "name": j.name,
                "message": j.message,
                "schedule": j.schedule,
                "channel": j.channel,
                "enabled": j.enabled,
                "timezone": j.timezone,
                "last_run": j.last_run.isoformat() if j.last_run else None,
                "metadata": j.metadata,
            }
            for j in jobs
        ]
        await asyncio.to_thread(_atomic_write_text, path, json.dumps(data, indent=2))
