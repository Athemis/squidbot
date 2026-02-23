"""Tests for search_history tool wiring in _make_agent_loop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def _minimal_llm_settings(s: object) -> None:
    """Populate a Settings instance with the minimal valid LLM config."""
    from squidbot.config.schema import (
        LLMModelConfig,
        LLMPoolEntry,
        LLMProviderConfig,
    )

    s.llm.providers["default"] = LLMProviderConfig(  # type: ignore[attr-defined]
        api_base="https://api.test", api_key="sk-test"
    )
    s.llm.models["default"] = LLMModelConfig(  # type: ignore[attr-defined]
        provider="default", model="test-model"
    )
    s.llm.pools["default"] = [LLMPoolEntry(model="default")]  # type: ignore[attr-defined]
    s.llm.default_pool = "default"  # type: ignore[attr-defined]


@pytest.fixture
def settings_search_history_enabled():
    from squidbot.config.schema import Settings

    s = Settings()
    _minimal_llm_settings(s)
    s.tools.search_history.enabled = True
    return s


@pytest.fixture
def settings_search_history_disabled():
    from squidbot.config.schema import Settings

    s = Settings()
    _minimal_llm_settings(s)
    s.tools.search_history.enabled = False
    return s


async def test_search_history_registered_when_enabled(
    settings_search_history_enabled, tmp_path: Path
) -> None:
    with (
        patch("squidbot.adapters.llm.openai.AsyncOpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        from squidbot.cli.main import _make_agent_loop

        loop, conns, _storage = await _make_agent_loop(
            settings_search_history_enabled,
            storage_dir=tmp_path,
        )
    names = [d.name for d in loop._registry.get_definitions()]
    assert "search_history" in names


async def test_search_history_not_registered_when_disabled(
    settings_search_history_disabled, tmp_path: Path
) -> None:
    with (
        patch("squidbot.adapters.llm.openai.AsyncOpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        from squidbot.cli.main import _make_agent_loop

        loop, conns, _storage = await _make_agent_loop(
            settings_search_history_disabled,
            storage_dir=tmp_path,
        )
    names = [d.name for d in loop._registry.get_definitions()]
    assert "search_history" not in names
