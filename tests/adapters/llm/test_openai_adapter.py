from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from squidbot.adapters.llm.openai import OpenAIAdapter


def _make_adapter(**kwargs: Any) -> OpenAIAdapter:
    with patch("squidbot.adapters.llm.openai.AsyncOpenAI"):
        return OpenAIAdapter(api_base="http://test", api_key="key", model="gpt-4", **kwargs)


def test_build_kwargs_minimal_non_streaming() -> None:
    adapter = _make_adapter()

    kwargs = adapter._build_kwargs(
        messages=[{"role": "user", "content": "hi"}], tools=None, stream=False
    )

    assert kwargs == {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "hi"}],
    }


def test_build_kwargs_includes_stream_flag_when_streaming() -> None:
    adapter = _make_adapter()

    kwargs = adapter._build_kwargs(
        messages=[{"role": "user", "content": "hi"}], tools=None, stream=True
    )

    assert kwargs == {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }


def test_build_kwargs_forwards_max_tokens() -> None:
    adapter = _make_adapter(max_tokens=123)

    kwargs = adapter._build_kwargs(
        messages=[{"role": "user", "content": "hi"}], tools=None, stream=False
    )

    assert kwargs["max_tokens"] == 123


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature", 0.7),
        ("top_p", 0.9),
        ("presence_penalty", 0.2),
        ("frequency_penalty", 0.4),
        ("reasoning_effort", "medium"),
        ("extra_body", {"provider": {"sort": "throughput"}}),
    ],
)
def test_build_kwargs_forwards_optional_parameter_when_set(field: str, value: Any) -> None:
    adapter = _make_adapter(**{field: value})

    kwargs = adapter._build_kwargs(
        messages=[{"role": "user", "content": "hi"}], tools=None, stream=False
    )

    assert kwargs[field] == value


def test_build_kwargs_omits_optional_parameters_when_none_or_empty() -> None:
    adapter = _make_adapter(
        max_tokens=None,
        temperature=None,
        top_p=None,
        presence_penalty=None,
        frequency_penalty=None,
        reasoning_effort=None,
        extra_body={},
    )

    kwargs = adapter._build_kwargs(
        messages=[{"role": "user", "content": "hi"}], tools=None, stream=False
    )

    assert "max_tokens" not in kwargs
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "presence_penalty" not in kwargs
    assert "frequency_penalty" not in kwargs
    assert "reasoning_effort" not in kwargs
    assert "extra_body" not in kwargs


def test_build_kwargs_includes_tools_only_when_provided() -> None:
    adapter = _make_adapter()

    with_tools = adapter._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "echo", "parameters": {}}}],
        stream=False,
    )
    without_tools = adapter._build_kwargs(
        messages=[{"role": "user", "content": "hi"}], tools=[], stream=False
    )

    assert "tools" in with_tools
    assert with_tools["tools"] == [
        {"type": "function", "function": {"name": "echo", "parameters": {}}}
    ]
    assert "tools" not in without_tools


def test_build_kwargs_all_params_set() -> None:
    adapter = _make_adapter(
        max_tokens=321,
        temperature=0.6,
        top_p=0.8,
        presence_penalty=0.1,
        frequency_penalty=0.3,
        reasoning_effort="high",
        extra_body={"provider": {"allow_fallbacks": False}},
    )

    kwargs = adapter._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "echo", "parameters": {}}}],
        stream=True,
    )

    assert kwargs == {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
        "tools": [{"type": "function", "function": {"name": "echo", "parameters": {}}}],
        "max_tokens": 321,
        "temperature": 0.6,
        "top_p": 0.8,
        "presence_penalty": 0.1,
        "frequency_penalty": 0.3,
        "reasoning_effort": "high",
        "extra_body": {"provider": {"allow_fallbacks": False}},
    }
