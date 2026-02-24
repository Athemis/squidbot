"""
JSONL-based persistence adapter.

Stores conversation history as a single global JSONL file (one message per line)
and memory documents as plain markdown files. Cron jobs are stored in a single
JSON file. Concurrent writes to history.jsonl are safe via fcntl.flock.

Directory layout:
    <base_dir>/
    ├── history.jsonl          # all channels, append-only
    ├── history.meta.json      # global consolidation cursor
    ├── memory/
    │   └── summary.md         # single global consolidation summary
    ├── workspace/
    │   └── MEMORY.md          # global cross-session memory (unchanged)
    └── cron/
        └── jobs.json           # scheduled task list (unchanged)
"""

from __future__ import annotations

import asyncio
import fcntl
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from squidbot.core.models import CronJob, Message, ToolCall


def _serialize_message(message: Message) -> str:
    """Serialize a Message to a JSON line."""
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
    """Deserialize a JSON line to a Message."""
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


def _history_file(base_dir: Path) -> Path:
    """Return the global history JSONL path, creating parent directories."""
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "history.jsonl"


def _history_meta_file(base_dir: Path) -> Path:
    """Return the global consolidation cursor path."""
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "history.meta.json"


def _global_summary_file(base_dir: Path, *, write: bool = False) -> Path:
    """Return the global consolidation summary path.

    Args:
        base_dir: Root storage directory.
        write: If True, creates parent directories.
    """
    path = base_dir / "memory" / "summary.md"
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


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
        path = _history_file(self._base)
        if not path.exists():
            return []
        messages = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                messages.append(deserialize_message(line))
        if last_n is not None:
            messages = messages[-last_n:]
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
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.write(_serialize_message(message) + "\n")
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

        await asyncio.to_thread(_write)

    async def load_global_memory(self) -> str:
        """Load the global cross-session memory document."""
        path = _global_memory_file(self._base)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    async def save_global_memory(self, content: str) -> None:
        """Overwrite the global memory document."""
        path = _global_memory_file(self._base, write=True)
        path.write_text(content, encoding="utf-8")

    async def load_global_summary(self) -> str:
        """Load the global consolidation summary."""
        path = _global_summary_file(self._base)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    async def save_global_summary(self, content: str) -> None:
        """Overwrite the global consolidation summary.

        Args:
            content: The summary text to persist.
        """
        path = _global_summary_file(self._base, write=True)
        path.write_text(content, encoding="utf-8")

    async def load_cron_jobs(self) -> list[CronJob]:
        """Load all scheduled jobs from the JSON file."""
        path = _cron_file(self._base)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        jobs = []
        for d in data:
            last_run = datetime.fromisoformat(d["last_run"]) if d.get("last_run") else None
            jobs.append(
                CronJob(
                    id=d["id"],
                    name=d["name"],
                    message=d["message"],
                    schedule=d["schedule"],
                    channel=d.get("channel", "cli:local"),
                    enabled=d.get("enabled", True),
                    timezone=d.get("timezone", "UTC"),
                    last_run=last_run,
                )
            )
        return jobs

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
            }
            for j in jobs
        ]
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    async def load_global_cursor(self) -> int:
        """Return the last_consolidated cursor, or 0 if no meta file exists."""
        path = _history_meta_file(self._base)
        if not path.exists():
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("last_consolidated", 0))

    async def save_global_cursor(self, cursor: int) -> None:
        """Write the last_consolidated cursor to history.meta.json.

        Args:
            cursor: The byte/line offset to persist.
        """
        path = _history_meta_file(self._base)
        path.write_text(json.dumps({"last_consolidated": cursor}), encoding="utf-8")
