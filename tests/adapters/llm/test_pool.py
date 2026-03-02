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


def test_adapters_with_same_base_and_key_share_client() -> None:
    """Two OpenAIAdapter instances with the same credentials must share one AsyncOpenAI client."""
    from unittest.mock import MagicMock, patch

    created_clients: list[MagicMock] = []

    def tracking_openai(**kwargs: object) -> MagicMock:
        client = MagicMock()
        created_clients.append(client)
        return client

    with patch("squidbot.adapters.llm.openai.AsyncOpenAI", side_effect=tracking_openai):
        from squidbot.adapters.llm.openai import OpenAIAdapter

        # The test for this must go through the gateway._resolve_llm path.
        # Instead, test OpenAIAdapter's `client` param directly:
        mock_client = MagicMock()
        a1 = OpenAIAdapter(
            api_base="https://api.example.com", api_key="key1", model="m1", client=mock_client
        )
        a2 = OpenAIAdapter(
            api_base="https://api.example.com", api_key="key1", model="m2", client=mock_client
        )

    # With shared client, AsyncOpenAI constructor should NOT be called
    assert len(created_clients) == 0, f"AsyncOpenAI was constructed {len(created_clients)} times"
    assert a1._client is mock_client
    assert a2._client is mock_client


def test_resolve_llm_shares_client_for_same_provider() -> None:
    """_resolve_llm must create one AsyncOpenAI client per unique (api_base, api_key)."""
    from unittest.mock import MagicMock, patch

    created_clients: list[MagicMock] = []

    def tracking_openai(**kwargs: object) -> MagicMock:
        client = MagicMock()
        created_clients.append(client)
        return client

    # Build minimal Settings-like objects for two pool entries on the same provider
    class FakeProvider:
        api_base = "https://api.example.com"
        api_key = "key1"
        supports_reasoning_content = False

    class FakeModel:
        provider = "main"
        model = "test-model"

    class FakeLLM:
        default_pool = "default"
        pools = {
            "default": [
                type("E", (), {"model": "m1"})(),
                type("E", (), {"model": "m2"})(),
            ]
        }
        models = {"m1": FakeModel(), "m2": FakeModel()}
        providers = {"main": FakeProvider()}

    class FakeSettings:
        llm = FakeLLM()

    with patch("openai.AsyncOpenAI", side_effect=tracking_openai):
        from squidbot.cli.gateway import _resolve_llm

        _resolve_llm(FakeSettings(), "default")  # type: ignore[arg-type]

    assert len(created_clients) == 1, (
        f"Expected 1 AsyncOpenAI client for same provider, got {len(created_clients)}"
    )
