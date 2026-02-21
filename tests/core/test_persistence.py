import asyncio
import json
import tempfile
from pathlib import Path
import pytest
from squidbot.core.models import Message, CronJob
from squidbot.adapters.persistence.jsonl import JsonlMemory


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def memory(tmp_dir):
    return JsonlMemory(base_dir=tmp_dir)


async def test_load_empty_history(memory):
    history = await memory.load_history("cli:local")
    assert history == []


async def test_append_and_load_message(memory):
    msg = Message(role="user", content="hello")
    await memory.append_message("cli:local", msg)
    history = await memory.load_history("cli:local")
    assert len(history) == 1
    assert history[0].content == "hello"
    assert history[0].role == "user"


async def test_multiple_messages_preserved_in_order(memory):
    msgs = [
        Message(role="user", content="first"),
        Message(role="assistant", content="second"),
        Message(role="user", content="third"),
    ]
    for m in msgs:
        await memory.append_message("cli:local", m)
    history = await memory.load_history("cli:local")
    assert [m.content for m in history] == ["first", "second", "third"]


async def test_memory_doc_empty_by_default(memory):
    doc = await memory.load_memory_doc("cli:local")
    assert doc == ""


async def test_memory_doc_save_and_load(memory):
    await memory.save_memory_doc("cli:local", "# Notes\n- User prefers short responses")
    doc = await memory.load_memory_doc("cli:local")
    assert "prefers short responses" in doc


async def test_cron_jobs_empty_by_default(memory):
    jobs = await memory.load_cron_jobs()
    assert jobs == []


async def test_cron_jobs_save_and_load(memory):
    job = CronJob(
        id="j1", name="morning", message="Good morning!", schedule="0 9 * * *", channel="cli:local"
    )
    await memory.save_cron_jobs([job])
    loaded = await memory.load_cron_jobs()
    assert len(loaded) == 1
    assert loaded[0].name == "morning"
    assert loaded[0].schedule == "0 9 * * *"
    assert loaded[0].channel == "cli:local"


async def test_sessions_are_isolated(memory):
    await memory.append_message("cli:local", Message(role="user", content="session A"))
    await memory.append_message("matrix:user", Message(role="user", content="session B"))
    cli_history = await memory.load_history("cli:local")
    matrix_history = await memory.load_history("matrix:user")
    assert len(cli_history) == 1
    assert cli_history[0].content == "session A"
    assert len(matrix_history) == 1
    assert matrix_history[0].content == "session B"
