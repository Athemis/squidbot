"""Tests for the spawn tool adapter."""

from __future__ import annotations

import asyncio

import pytest

from squidbot.adapters.tools.spawn import CollectingChannel, JobStore
from squidbot.core.models import OutboundMessage, Session


@pytest.fixture
def session() -> Session:
    return Session(channel="test", sender_id="user1")


async def test_collecting_channel_not_streaming():
    ch = CollectingChannel()
    assert ch.streaming is False


async def test_collecting_channel_collects_text(session):
    ch = CollectingChannel()
    msg = OutboundMessage(session=session, text="hello")
    await ch.send(msg)
    assert ch.collected_text == "hello"


async def test_collecting_channel_collects_multiple(session):
    ch = CollectingChannel()
    await ch.send(OutboundMessage(session=session, text="foo"))
    await ch.send(OutboundMessage(session=session, text="bar"))
    assert ch.collected_text == "foobar"


async def test_collecting_channel_receive_yields_nothing():
    ch = CollectingChannel()
    items = [msg async for msg in ch.receive()]
    assert items == []


async def test_collecting_channel_send_typing_is_noop(session):
    ch = CollectingChannel()
    await ch.send_typing(session.id)  # must not raise


async def test_job_store_start_and_await():
    store = JobStore()

    async def work() -> str:
        return "result"

    store.start("job1", work())
    results = await store.await_jobs(["job1"])
    assert results == {"job1": "result"}


async def test_job_store_await_multiple():
    store = JobStore()

    async def slow() -> str:
        await asyncio.sleep(0)
        return "slow"

    async def fast() -> str:
        return "fast"

    store.start("a", fast())
    store.start("b", slow())
    results = await store.await_jobs(["a", "b"])
    assert results["a"] == "fast"
    assert results["b"] == "slow"


async def test_job_store_exception_captured():
    store = JobStore()

    async def boom() -> str:
        raise ValueError("oops")

    store.start("bad", boom())
    results = await store.await_jobs(["bad"])
    assert isinstance(results["bad"], ValueError)


async def test_job_store_unknown_job_id():
    store = JobStore()
    results = await store.await_jobs(["nonexistent"])
    assert results == {}


async def test_job_store_all_job_ids():
    store = JobStore()

    async def noop() -> str:
        return ""

    store.start("x", noop())
    store.start("y", noop())
    assert set(store.all_job_ids()) == {"x", "y"}
