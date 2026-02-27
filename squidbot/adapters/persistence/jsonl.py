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
import fcntl
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
    if message.channel is not None:
        d["channel"] = message.channel
    if message.sender_id is not None:
        d["sender_id"] = message.sender_id
    return json.dumps(d)


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
    """Return the global history JSONL path, creating parent directories."""
    # This helper is used by both readers and writers. Creating the base directory is
    # cheap and simplifies callers by ensuring a stable path.
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "history.jsonl"


def _global_memory_file(base_dir: Path, *, write: bool = False) -> Path:
    """Return the global MEMORY.md path.

    Args:
        base_dir: Root storage directory.
        write: If True, creates parent directories.
    """
    path = base_dir / "workspace" / "MEMORY.md"
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _cron_file(base_dir: Path) -> Path:
    """Return the cron jobs JSON path."""
    path = base_dir / "cron" / "jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


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

    async def load_history(self, last_n: int | None = None) -> list[Message]:
        """Load messages from the global history JSONL file.

        Args:
            last_n: If provided, return only the last N messages. If None, return all.

        Returns:
            List of messages in chronological order.
        """
        # Treat <=0 as "no history". This is useful for callers that want to disable
        # history without branching. It also prevents accidentally loading the full
        # file via Python slicing semantics (e.g. all_messages[-0:] == all_messages).
        if last_n is not None and last_n <= 0:
            return []

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
        path = _global_memory_file(self._base, write=True)
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
