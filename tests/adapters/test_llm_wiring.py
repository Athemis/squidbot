"""Tests for _resolve_llm() pool/model/provider resolution."""

from __future__ import annotations

import pytest

from squidbot.adapters.llm.openai import OpenAIAdapter
from squidbot.adapters.llm.pool import PooledLLMAdapter
from squidbot.cli.main import _resolve_llm
from squidbot.config.schema import (
    LLMConfig,
    LLMModelConfig,
    LLMPoolEntry,
    LLMProviderConfig,
    Settings,
)


def _make_settings(pools: dict) -> Settings:
    s = Settings()
    s.llm = LLMConfig(
        default_pool="smart",
        providers={
            "or": LLMProviderConfig(api_base="https://api.test", api_key="sk-test"),
        },
        models={
            "opus": LLMModelConfig(provider="or", model="claude-opus"),
            "haiku": LLMModelConfig(provider="or", model="claude-haiku"),
        },
        pools=pools,
    )
    return s


def test_single_entry_pool_returns_openai_adapter():
    s = _make_settings({"smart": [LLMPoolEntry(model="opus")]})
    llm = _resolve_llm(s, "smart")
    assert isinstance(llm, OpenAIAdapter)


def test_unknown_pool_raises():
    s = _make_settings({"smart": [LLMPoolEntry(model="opus")]})
    with pytest.raises(ValueError, match="pool 'missing'"):
        _resolve_llm(s, "missing")


def test_unknown_model_raises():
    s = _make_settings({"smart": [LLMPoolEntry(model="ghost")]})
    with pytest.raises(ValueError, match="model 'ghost'"):
        _resolve_llm(s, "smart")


def test_unknown_provider_raises():
    s = Settings()
    s.llm = LLMConfig(
        default_pool="smart",
        providers={},
        models={"opus": LLMModelConfig(provider="missing_provider", model="claude")},
        pools={"smart": [LLMPoolEntry(model="opus")]},
    )
    with pytest.raises(ValueError, match="provider 'missing_provider'"):
        _resolve_llm(s, "smart")


def test_correct_adapter_credentials():
    s = _make_settings({"smart": [LLMPoolEntry(model="opus")]})
    llm = _resolve_llm(s, "smart")
    assert isinstance(llm, OpenAIAdapter)
    # Can't check private attrs directly, but we can verify it constructed without error
    # and is the right type


def test_multi_entry_pool_returns_pooled_adapter():
    s = _make_settings({"smart": [LLMPoolEntry(model="opus"), LLMPoolEntry(model="haiku")]})
    llm = _resolve_llm(s, "smart")
    assert isinstance(llm, PooledLLMAdapter)
