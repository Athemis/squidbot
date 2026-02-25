"""Tests for the global (non-session-scoped) JsonlMemory API."""

from __future__ import annotations

from pathlib import Path

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
