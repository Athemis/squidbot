"""Tests for spawn tool wiring in _make_agent_loop."""

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
def settings_with_spawn():
    from squidbot.config.schema import Settings, SpawnProfile

    s = Settings()
    _minimal_llm_settings(s)
    s.tools.spawn.enabled = True
    s.tools.spawn.profiles = {
        "coder": SpawnProfile(system_prompt="You are a coder.", tools=["shell"]),
    }
    return s


@pytest.fixture
def settings_spawn_disabled():
    from squidbot.config.schema import Settings

    s = Settings()
    _minimal_llm_settings(s)
    s.tools.spawn.enabled = False
    return s


async def test_spawn_tools_registered_when_enabled(settings_with_spawn, tmp_path):
    with (
        patch("squidbot.adapters.llm.openai.AsyncOpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        from squidbot.cli.main import _make_agent_loop

        loop, conns, _storage = await _make_agent_loop(
            settings_with_spawn,
            storage_dir=tmp_path,
        )
    names = [d.name for d in loop._registry.get_definitions()]
    assert "spawn" in names
    assert "spawn_await" in names


async def test_spawn_tools_not_registered_when_disabled(settings_spawn_disabled, tmp_path):
    with (
        patch("squidbot.adapters.llm.openai.AsyncOpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        from squidbot.cli.main import _make_agent_loop

        loop, conns, _storage = await _make_agent_loop(
            settings_spawn_disabled,
            storage_dir=tmp_path,
        )
    names = [d.name for d in loop._registry.get_definitions()]
    assert "spawn" not in names
    assert "spawn_await" not in names


async def test_profile_injected_in_system_prompt(settings_with_spawn, tmp_path):
    with (
        patch("squidbot.adapters.llm.openai.AsyncOpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        from squidbot.cli.main import _make_agent_loop

        loop, _, _storage = await _make_agent_loop(settings_with_spawn, storage_dir=tmp_path)
    assert "coder" in loop._system_prompt
    assert "<available_spawn_profiles>" in loop._system_prompt


async def test_no_profile_injection_when_no_profiles(tmp_path):
    from squidbot.config.schema import Settings

    s = Settings()
    _minimal_llm_settings(s)
    s.tools.spawn.enabled = True
    # no profiles
    with (
        patch("squidbot.adapters.llm.openai.AsyncOpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        from squidbot.cli.main import _make_agent_loop

        loop, _, _storage = await _make_agent_loop(s, storage_dir=tmp_path)
    assert "<available_spawn_profiles>" not in loop._system_prompt
