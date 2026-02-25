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
