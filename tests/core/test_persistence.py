import pytest

from squidbot.adapters.persistence.jsonl import JsonlMemory
from squidbot.core.models import CronJob, Message


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def memory(tmp_dir):
    return JsonlMemory(base_dir=tmp_dir)


async def test_load_empty_history(memory):
    history = await memory.load_history()
    assert history == []


async def test_append_and_load_message(memory):
    msg = Message(role="user", content="hello")
    await memory.append_message(msg)
    history = await memory.load_history()
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
        await memory.append_message(m)
    history = await memory.load_history()
    assert [m.content for m in history] == ["first", "second", "third"]


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


async def test_messages_from_all_channels_in_global_history(memory):
    await memory.append_message(Message(role="user", content="from cli", channel="cli:local"))
    await memory.append_message(Message(role="user", content="from matrix", channel="matrix:user"))
    history = await memory.load_history()
    assert len(history) == 2
    assert history[0].content == "from cli"
    assert history[1].content == "from matrix"


async def test_load_history_last_n(memory):
    for i in range(5):
        await memory.append_message(Message(role="user", content=str(i)))
    history = await memory.load_history(last_n=3)
    assert [m.content for m in history] == ["2", "3", "4"]
