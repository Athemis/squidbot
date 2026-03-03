"""Tests for gateway _resolve_llm inference-parameter forwarding."""

from __future__ import annotations

from unittest.mock import patch

from squidbot.cli.gateway import _resolve_llm
from squidbot.config.schema import (
    LLMConfig,
    LLMModelConfig,
    LLMPoolEntry,
    LLMProviderConfig,
    Settings,
)


def _make_settings(model_cfg: LLMModelConfig) -> Settings:
    settings = Settings()
    settings.llm = LLMConfig(
        default_pool="default",
        providers={"openrouter": LLMProviderConfig(api_base="https://api.test", api_key="sk-test")},
        models={"primary": model_cfg},
        pools={"default": [LLMPoolEntry(model="primary")]},
    )
    return settings


def test_resolve_llm_forwards_temperature() -> None:
    settings = _make_settings(
        LLMModelConfig(provider="openrouter", model="gpt-test", temperature=0.35)
    )

    with patch("squidbot.adapters.llm.openai.OpenAIAdapter") as openai_adapter:
        _resolve_llm(settings, "default")

    assert openai_adapter.call_args.kwargs["temperature"] == 0.35


def test_resolve_llm_forwards_top_p() -> None:
    settings = _make_settings(LLMModelConfig(provider="openrouter", model="gpt-test", top_p=0.7))

    with patch("squidbot.adapters.llm.openai.OpenAIAdapter") as openai_adapter:
        _resolve_llm(settings, "default")

    assert openai_adapter.call_args.kwargs["top_p"] == 0.7


def test_resolve_llm_forwards_reasoning_effort() -> None:
    settings = _make_settings(
        LLMModelConfig(provider="openrouter", model="gpt-test", reasoning_effort="high")
    )

    with patch("squidbot.adapters.llm.openai.OpenAIAdapter") as openai_adapter:
        _resolve_llm(settings, "default")

    assert openai_adapter.call_args.kwargs["reasoning_effort"] == "high"


def test_resolve_llm_forwards_extra_body() -> None:
    extra_body = {"provider": {"sort": "price"}}
    settings = _make_settings(
        LLMModelConfig(provider="openrouter", model="gpt-test", extra_body=extra_body)
    )

    with patch("squidbot.adapters.llm.openai.OpenAIAdapter") as openai_adapter:
        _resolve_llm(settings, "default")

    assert openai_adapter.call_args.kwargs["extra_body"] == extra_body


def test_resolve_llm_forwards_explicit_max_tokens_override() -> None:
    settings = _make_settings(
        LLMModelConfig(provider="openrouter", model="gpt-test", max_tokens=1234)
    )

    with patch("squidbot.adapters.llm.openai.OpenAIAdapter") as openai_adapter:
        _resolve_llm(settings, "default")

    assert openai_adapter.call_args.kwargs["max_tokens"] == 1234


def test_resolve_llm_forwards_inference_defaults() -> None:
    settings = _make_settings(LLMModelConfig(provider="openrouter", model="gpt-test"))

    with patch("squidbot.adapters.llm.openai.OpenAIAdapter") as openai_adapter:
        _resolve_llm(settings, "default")

    call_kwargs = openai_adapter.call_args.kwargs
    assert call_kwargs["max_tokens"] == 8192
    assert call_kwargs["temperature"] is None
    assert call_kwargs["top_p"] is None
    assert call_kwargs["reasoning_effort"] is None
    assert call_kwargs["extra_body"] == {}
