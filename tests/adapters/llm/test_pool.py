"""Tests for PooledLLMAdapter sequential fallback behaviour."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from squidbot.adapters.llm.pool import PooledLLMAdapter, _is_auth_error
from squidbot.core.models import Message


def _make_streaming_adapter(chunks: list[str]):
    """Build a mock LLMPort that yields the given chunks."""

    class StreamingAdapter:
        async def chat(self, messages, tools, *, stream=True):
            async def _gen():
                for chunk in chunks:
                    yield chunk

            return _gen()

    return StreamingAdapter()


def _make_failing_adapter(exc: Exception):
    """Build a mock LLMPort that raises the given exception."""

    class FailingAdapter:
        async def chat(self, messages, tools, *, stream=True):
            raise exc

    return FailingAdapter()


async def _collect(pool, messages=None, tools=None):
    if messages is None:
        messages = [Message(role="user", content="hi")]
    if tools is None:
        tools = []
    result = []
    async for chunk in await pool.chat(messages, tools):
        result.append(chunk)
    return result


async def test_single_adapter_delegates():
    adapter = _make_streaming_adapter(["hello", " world"])
    pool = PooledLLMAdapter([adapter])
    result = await _collect(pool)
    assert result == ["hello", " world"]


async def test_first_succeeds_second_never_called():
    called = []

    class TrackingAdapter:
        async def chat(self, messages, tools, *, stream=True):
            called.append("second")

            async def _gen():
                yield "fallback"

            return _gen()

    a1 = _make_streaming_adapter(["ok"])
    pool = PooledLLMAdapter([a1, TrackingAdapter()])
    result = await _collect(pool)
    assert result == ["ok"]
    assert called == []


async def test_first_fails_second_called():
    a1 = _make_failing_adapter(RuntimeError("timeout"))
    a2 = _make_streaming_adapter(["fallback"])
    pool = PooledLLMAdapter([a1, a2])
    result = await _collect(pool)
    assert result == ["fallback"]


async def test_auth_error_logs_warning():
    class AuthenticationError(Exception):
        pass

    a1 = _make_failing_adapter(AuthenticationError("bad key"))
    a2 = _make_streaming_adapter(["ok"])
    pool = PooledLLMAdapter([a1, a2])
    with patch("squidbot.adapters.llm.pool.logger") as mock_log:
        result = await _collect(pool)
    assert result == ["ok"]
    mock_log.warning.assert_called_once()
    mock_log.info.assert_not_called()


async def test_generic_error_logs_info_not_warning():
    a1 = _make_failing_adapter(RuntimeError("connection refused"))
    a2 = _make_streaming_adapter(["ok"])
    pool = PooledLLMAdapter([a1, a2])
    with patch("squidbot.adapters.llm.pool.logger") as mock_log:
        result = await _collect(pool)
    assert result == ["ok"]
    mock_log.warning.assert_not_called()
    mock_log.info.assert_called_once()


async def test_all_fail_raises_last():
    a1 = _make_failing_adapter(RuntimeError("first"))
    a2 = _make_failing_adapter(RuntimeError("second"))
    pool = PooledLLMAdapter([a1, a2])
    with pytest.raises(RuntimeError, match="second"):
        await _collect(pool)


def test_auth_error_detected_by_name():
    class AuthenticationError(Exception):
        pass

    assert _is_auth_error(AuthenticationError("x")) is True
    assert _is_auth_error(RuntimeError("x")) is False


def test_empty_adapters_raises():
    with pytest.raises(ValueError, match="at least one"):
        PooledLLMAdapter([])
