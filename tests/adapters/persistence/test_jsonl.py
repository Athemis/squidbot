"""Tests for the global (non-session-scoped) JsonlMemory API."""

from __future__ import annotations

from pathlib import Path

import pytest

from squidbot.adapters.persistence.jsonl import JsonlMemory
from squidbot.core.models import Message


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
async def test_global_summary_roundtrip(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_global_summary("summary text")
    assert await storage.load_global_summary() == "summary text"


@pytest.mark.asyncio
async def test_global_cursor_roundtrip(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    assert await storage.load_global_cursor() == 0
    await storage.save_global_cursor(42)
    assert await storage.load_global_cursor() == 42


@pytest.mark.asyncio
async def test_message_channel_sender_roundtrip(tmp_path: Path) -> None:
    storage = JsonlMemory(base_dir=tmp_path)
    msg = Message(role="assistant", content="hi", channel="matrix", sender_id="@bot:matrix.org")
    await storage.append_message(msg)
    loaded = await storage.load_history()
    assert loaded[0].channel == "matrix"
    assert loaded[0].sender_id == "@bot:matrix.org"
