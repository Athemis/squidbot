"""Tests for the global (non-session-scoped) JsonlMemory API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from squidbot.adapters.persistence.jsonl import JsonlMemory
from squidbot.core.models import CronJob, Message


@pytest.mark.asyncio
async def test_global_history_empty_on_new_storage(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    history = await storage.load_history()
    assert history == []


@pytest.mark.asyncio
async def test_append_and_load_history(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    msg = Message(role="user", content="hello", channel="cli", sender_id="local")
    await storage.append_message(msg)
    history = await storage.load_history()
    assert len(history) == 1
    assert history[0].channel == "cli"
    assert history[0].sender_id == "local"


@pytest.mark.asyncio
async def test_load_history_returns_last_n(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    for i in range(5):
        await storage.append_message(
            Message(role="user", content=str(i), channel="cli", sender_id="local")
        )
    history = await storage.load_history(last_n=3)
    assert len(history) == 3
    assert history[0].content == "2"


@pytest.mark.asyncio
async def test_load_history_skips_malformed_jsonl_line(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.append_message(Message(role="user", content="ok-1"))

    history_path = tmp_path / "history.jsonl"
    with history_path.open("a", encoding="utf-8") as f:
        f.write("{ this is not valid json }\n")

    await storage.append_message(Message(role="assistant", content="ok-2"))

    history = await storage.load_history()
    assert [message.content for message in history] == ["ok-1", "ok-2"]


@pytest.mark.asyncio
async def test_load_history_tolerates_invalid_utf8_bytes(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.append_message(Message(role="user", content="before-bytes"))

    history_path = tmp_path / "history.jsonl"
    with history_path.open("ab") as f:
        f.write(b"\xff\xfe\xfa\n")

    await storage.append_message(Message(role="assistant", content="after-bytes"))

    history = await storage.load_history()
    assert [message.content for message in history] == ["before-bytes", "after-bytes"]


@pytest.mark.asyncio
async def test_summary_and_cursor_api_removed(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    assert not hasattr(storage, "load_global_summary")
    assert not hasattr(storage, "save_global_summary")
    assert not hasattr(storage, "load_global_cursor")
    assert not hasattr(storage, "save_global_cursor")


@pytest.mark.asyncio
async def test_message_channel_sender_roundtrip(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    msg = Message(role="assistant", content="hi", channel="matrix", sender_id="@bot:matrix.org")
    await storage.append_message(msg)
    loaded = await storage.load_history()
    assert loaded[0].channel == "matrix"
    assert loaded[0].sender_id == "@bot:matrix.org"


@pytest.mark.asyncio
async def test_message_reasoning_content_roundtrip(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    msg = Message(
        role="assistant",
        content="",
        reasoning_content="tool selection reasoning",
        channel="cli",
        sender_id="assistant",
    )
    await storage.append_message(msg)
    loaded = await storage.load_history()
    assert loaded[0].reasoning_content == "tool selection reasoning"


@pytest.mark.asyncio
async def test_global_memory_roundtrip(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_global_memory("facts")
    assert await storage.load_global_memory() == "facts"


@pytest.mark.asyncio
async def test_cron_jobs_roundtrip(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    job = CronJob(
        id="job-1",
        name="Daily",
        message="ping",
        schedule="0 9 * * *",
        channel="cli:local",
    )
    await storage.save_cron_jobs([job])
    loaded = await storage.load_cron_jobs()
    assert len(loaded) == 1
    assert loaded[0].id == "job-1"
    assert loaded[0].message == "ping"
    assert loaded[0].timezone == "local"


@pytest.mark.asyncio
async def test_load_cron_jobs_invalid_json_returns_empty(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    cron_path = tmp_path / "cron" / "jobs.json"
    cron_path.parent.mkdir(parents=True, exist_ok=True)
    cron_path.write_text("{not-valid-json", encoding="utf-8")

    assert await storage.load_cron_jobs() == []


@pytest.mark.asyncio
async def test_load_history_last_n_zero(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.append_message(Message(role="user", content="hello"))
    history = await storage.load_history(last_n=0)
    assert history == []
    history = await storage.load_history(last_n=-1)
    assert history == []


class _CountingBinaryFile:
    def __init__(self, wrapped: Any, counter: dict[str, int]) -> None:
        self._wrapped = wrapped
        self._counter = counter

    def __enter__(self) -> _CountingBinaryFile:
        self._wrapped.__enter__()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool | None:
        return self._wrapped.__exit__(exc_type, exc, tb)

    def read(self, size: int = -1) -> bytes:
        data = self._wrapped.read(size)
        self._counter["bytes"] += len(data)
        return data

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


def _write_history_fixture(path: Path, total_messages: int) -> None:
    with path.open("wb") as f:
        for i in range(total_messages):
            payload = {
                "role": "user",
                "content": f"m{i:06d}",
                "timestamp": "2026-01-01T00:00:00",
            }
            f.write(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")


@pytest.mark.asyncio
async def test_load_history_last_n_reads_bounded_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    history_path = tmp_path / "history.jsonl"

    _write_history_fixture(history_path, total_messages=180_000)
    assert history_path.stat().st_size >= 8 * 1024 * 1024

    bytes_counter = {"bytes": 0}
    original_open = Path.open

    def counting_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        mode = args[0] if args else kwargs.get("mode", "r")
        opened = original_open(self, *args, **kwargs)
        if self == history_path and mode == "rb":
            return _CountingBinaryFile(opened, bytes_counter)
        return opened

    monkeypatch.setattr(Path, "open", counting_open)

    history = await storage.load_history(last_n=80)

    assert len(history) == 80
    assert history[0].content == "m179920"
    assert history[-1].content == "m179999"
    assert bytes_counter["bytes"] <= 1_048_576


@pytest.mark.asyncio
async def test_load_history_last_n_skips_malformed_trailing_lines(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    history_path = tmp_path / "history.jsonl"

    _write_history_fixture(history_path, total_messages=200)
    with history_path.open("ab") as f:
        f.write(b"{ this is malformed json }\n")
        f.write(b"\xff\xfe\xfa\n")

    history = await storage.load_history(last_n=80)

    assert len(history) == 80
    assert history[0].content == "m000120"
    assert history[-1].content == "m000199"


@pytest.mark.asyncio
async def test_no_mkdir_after_init(tmp_path: Path) -> None:
    """mkdir must not be called after __init__ completes."""
    from unittest.mock import patch

    mkdir_calls: list[Path] = []
    original_mkdir = Path.mkdir

    def tracking_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        mkdir_calls.append(self)
        original_mkdir(self, *args, **kwargs)  # type: ignore[arg-type]  # Path.mkdir uses bool params, not object

    mem = JsonlMemory(base_dir=tmp_path / "store")  # __init__ may call mkdir
    mkdir_calls.clear()  # reset after __init__

    with patch.object(Path, "mkdir", tracking_mkdir):
        await mem.load_history(last_n=10)
        await mem.append_message(Message(role="user", content="hi", channel="cli", sender_id="x"))

    assert mkdir_calls == [], f"mkdir called after __init__: {mkdir_calls}"


@pytest.mark.asyncio
async def test_load_history_uses_cache_after_first_load(tmp_path: Path) -> None:
    """After the first load_history call no disk read occurs for subsequent calls."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.core.models import Message

    mem = JsonlMemory(base_dir=tmp_path)
    msg = Message(role="user", content="cached?", channel="cli", sender_id="u")

    # Write one message to disk
    await mem.append_message(msg)

    # First load: reads from disk, populates cache
    result1 = await mem.load_history(last_n=10)
    assert len(result1) == 1

    # Delete the history file — second load must come from cache
    history_path = tmp_path / "history.jsonl"
    history_path.unlink()
    assert not history_path.exists()

    result2 = await mem.load_history(last_n=10)
    assert len(result2) == 1
    assert result2[0].content == "cached?"


@pytest.mark.asyncio
async def test_load_history_cache_miss_when_last_n_grows(tmp_path: Path) -> None:
    """Cache must miss and re-read disk when last_n exceeds the cached window."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.core.models import Message

    mem = JsonlMemory(base_dir=tmp_path)
    for i in range(5):
        await mem.append_message(
            Message(role="user", content=f"msg{i}", channel="cli", sender_id="u")
        )

    # First load: cache window = 3
    result1 = await mem.load_history(last_n=3)
    assert len(result1) == 3

    # Now add two more messages directly to the file (bypass cache) to verify re-read
    # Actually: write two more via append_message (which also updates cache)
    await mem.append_message(Message(role="user", content="extra1", channel="cli", sender_id="u"))
    await mem.append_message(Message(role="user", content="extra2", channel="cli", sender_id="u"))

    # Request larger window — must re-read disk (cache window was only 3)
    result2 = await mem.load_history(last_n=5)
    assert len(result2) == 5
    # The cache should now be updated to window=5
    assert mem._history_cache_size == 5


@pytest.mark.asyncio
async def test_append_message_updates_cache(tmp_path: Path) -> None:
    """append_message must keep the cache current for subsequent cache hits."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.core.models import Message

    mem = JsonlMemory(base_dir=tmp_path)
    msg1 = Message(role="user", content="first", channel="cli", sender_id="u")
    await mem.append_message(msg1)

    # Prime the cache
    result1 = await mem.load_history(last_n=10)
    assert len(result1) == 1

    # Append via cache-maintaining path
    msg2 = Message(role="user", content="second", channel="cli", sender_id="u")
    await mem.append_message(msg2)

    # Delete file to force cache-only path
    (tmp_path / "history.jsonl").unlink()

    result2 = await mem.load_history(last_n=10)
    assert len(result2) == 2
    assert result2[0].content == "first"
    assert result2[1].content == "second"


@pytest.mark.asyncio
async def test_persist_exchange_opens_file_once(tmp_path: Path) -> None:
    """persist_exchange must open history.jsonl only once."""
    from unittest.mock import patch

    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.core.memory import MemoryManager

    mem = JsonlMemory(base_dir=tmp_path)
    manager = MemoryManager(storage=mem)  # type: ignore[arg-type]

    open_count = 0
    real_open = open

    def counting_open(path: object, *args: object, **kwargs: object) -> Any:
        nonlocal open_count
        if "history.jsonl" in str(path):
            open_count += 1
        return real_open(path, *args, **kwargs)  # type: ignore[call-overload]

    with patch("builtins.open", side_effect=counting_open):
        await manager.persist_exchange(
            channel="cli",
            sender_id="user",
            user_message="hello",
            assistant_reply="world",
        )

    assert open_count == 1, f"history.jsonl was opened {open_count} times"
