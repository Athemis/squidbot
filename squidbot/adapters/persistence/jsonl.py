"""
JSONL-based persistence adapter.

Stores conversation history as JSONL files (one message per line) and
memory documents as plain markdown files. Cron jobs are stored in a single
JSON file.

Directory layout:
    <base_dir>/
    ├── sessions/
    │   ├── <session-id>.jsonl      # conversation history
    │   └── <session-id>.meta.json  # consolidation cursor
    ├── memory/
    │   └── <session-id>/
    │       └── memory.md         # agent-maintained notes
    └── cron/
        └── jobs.json             # scheduled task list
"""

from __future__ import annotations

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
    )


def _session_file(base_dir: Path, session_id: str) -> Path:
    """Return the JSONL path for a session, creating parent directories."""
    # Replace ":" with "__" for safe filesystem paths
    safe_id = session_id.replace(":", "__")
    path = base_dir / "sessions" / f"{safe_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _meta_file(base_dir: Path, session_id: str, *, write: bool = False) -> Path:
    """Return the .meta.json path for a session.

    Args:
        base_dir: Root storage directory.
        session_id: Session identifier (colons replaced with '__' for filesystem safety).
        write: If True, creates parent directories. Set to True only on write paths.
    """
    safe_id = session_id.replace(":", "__")
    path = base_dir / "sessions" / f"{safe_id}.meta.json"
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

    All I/O is synchronous (no async file I/O library needed at this scale).
    Methods are async to satisfy the MemoryPort protocol.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    async def load_history(self, session_id: str) -> list[Message]:
        """Load all messages for a session from its JSONL file."""
        path = _session_file(self._base, session_id)
        if not path.exists():
            return []
        messages = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                messages.append(deserialize_message(line))
        return messages

    async def append_message(self, session_id: str, message: Message) -> None:
        """Append a single message to the session's JSONL file."""
        path = _session_file(self._base, session_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(_serialize_message(message) + "\n")

    async def load_global_memory(self) -> str:
        """Not yet implemented — added in Task B2."""
        raise NotImplementedError

    async def save_global_memory(self, content: str) -> None:
        """Not yet implemented — added in Task B2."""
        raise NotImplementedError

    async def load_session_summary(self, session_id: str) -> str:
        """Not yet implemented — added in Task B2."""
        raise NotImplementedError

    async def save_session_summary(self, session_id: str, content: str) -> None:
        """Not yet implemented — added in Task B2."""
        raise NotImplementedError

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
        """Persist the full job list."""
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

    async def load_consolidated_cursor(self, session_id: str) -> int:
        """Return the last_consolidated cursor, or 0 if no meta file exists."""
        path = _meta_file(self._base, session_id)
        if not path.exists():
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("last_consolidated", 0))

    async def save_consolidated_cursor(self, session_id: str, cursor: int) -> None:
        """Write the last_consolidated cursor to .meta.json."""
        path = _meta_file(self._base, session_id, write=True)
        path.write_text(json.dumps({"last_consolidated": cursor}), encoding="utf-8")
