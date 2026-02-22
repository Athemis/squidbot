"""Tests for the spawn tool adapter."""

from __future__ import annotations

import pytest

from squidbot.adapters.tools.spawn import CollectingChannel
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
