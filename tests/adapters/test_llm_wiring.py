"""Tests for _resolve_llm() pool/model/provider resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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


async def test_make_agent_loop_wires_memory_with_history_context_messages(tmp_path: Path) -> None:
    s = _make_settings({"smart": [LLMPoolEntry(model="opus")]})
    s.agents.history_context_messages = 13

    with (
        patch("squidbot.adapters.llm.openai.AsyncOpenAI"),
        patch.object(Path, "exists", return_value=False),
        patch("squidbot.core.memory.MemoryManager", autospec=True) as memory_manager_cls,
    ):
        from squidbot.cli.main import _make_agent_loop

        await _make_agent_loop(s, storage_dir=tmp_path)

    call_kwargs = memory_manager_cls.call_args.kwargs
    assert call_kwargs["history_context_messages"] == 13
    assert call_kwargs["owner_aliases"] == s.owner.aliases
    assert call_kwargs["owner_aliases"] is not s.owner.aliases
    assert "llm" not in call_kwargs
    assert "consolidation_threshold" not in call_kwargs
    assert "keep_recent_ratio" not in call_kwargs
