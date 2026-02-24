"""Tests for context budget wiring in _make_agent_loop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


def _minimal_llm_settings(s: object) -> None:
    """Populate a Settings instance with the minimal valid LLM config."""
    from squidbot.config.schema import (
        LLMModelConfig,
        LLMPoolEntry,
        LLMProviderConfig,
    )

    s.llm.providers["default"] = LLMProviderConfig(  # type: ignore[attr-defined]
        api_base="https://api.test",
        api_key="sk-test",
    )
    s.llm.models["default"] = LLMModelConfig(  # type: ignore[attr-defined]
        provider="default",
        model="test-model",
    )
    s.llm.pools["default"] = [LLMPoolEntry(model="default")]  # type: ignore[attr-defined]
    s.llm.default_pool = "default"  # type: ignore[attr-defined]


async def test_context_budget_settings_are_passed_to_memory_manager(tmp_path: Path) -> None:
    from squidbot.config.schema import Settings

    settings = Settings()
    _minimal_llm_settings(settings)
    settings.agents.context_budget_mode = "words"
    settings.agents.context_memory_max_words = 111
    settings.agents.context_summary_max_words = 222
    settings.agents.context_history_max_words = 333
    settings.agents.context_total_max_words = 444
    settings.agents.context_dedupe_summary_against_memory = False
    settings.agents.context_min_recent_messages = 3

    with (
        patch("squidbot.adapters.llm.openai.AsyncOpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        from squidbot.cli.main import _make_agent_loop

        loop, _conns, _storage = await _make_agent_loop(settings, storage_dir=tmp_path)

    memory = loop._memory
    assert memory._context_budget_mode == "words"
    assert memory._context_memory_max_words == 111
    assert memory._context_summary_max_words == 222
    assert memory._context_history_max_words == 333
    assert memory._context_total_max_words == 444
    assert memory._context_dedupe_summary_against_memory is False
    assert memory._context_min_recent_messages == 3
