import json

import pytest

from squidbot.config.schema import (
    AgentConfig,
    HeartbeatConfig,
    LLMConfig,
    LLMModelConfig,
    LLMPoolEntry,
    LLMProviderConfig,
    Settings,
    SpawnProfile,
    SpawnSettings,
    ToolsConfig,
)


def test_llm_config_defaults():
    cfg = LLMConfig()
    assert cfg.default_pool == "default"
    assert cfg.providers == {}
    assert cfg.models == {}
    assert cfg.pools == {}


def test_llm_provider_config():
    p = LLMProviderConfig(api_base="https://openrouter.ai/api/v1", api_key="sk-test")
    assert p.api_base == "https://openrouter.ai/api/v1"
    assert p.api_key == "sk-test"


def test_llm_model_config_defaults():
    m = LLMModelConfig(provider="openrouter", model="anthropic/claude-opus-4-5")
    assert m.max_tokens == 8192
    assert m.max_context_tokens == 100_000


def test_llm_pool_entry():
    e = LLMPoolEntry(model="opus")
    assert e.model == "opus"


def test_settings_full_pool_config():
    raw = {
        "llm": {
            "default_pool": "smart",
            "providers": {
                "openrouter": {"api_base": "https://openrouter.ai/api/v1", "api_key": "sk-test"}
            },
            "models": {"opus": {"provider": "openrouter", "model": "anthropic/claude-opus-4-5"}},
            "pools": {"smart": [{"model": "opus"}]},
        }
    }
    s = Settings.model_validate(raw)
    assert s.llm.default_pool == "smart"
    assert s.llm.providers["openrouter"].api_key == "sk-test"
    assert s.llm.models["opus"].model == "anthropic/claude-opus-4-5"
    assert s.llm.pools["smart"][0].model == "opus"


def test_heartbeat_config_pool_default():
    cfg = HeartbeatConfig()
    assert cfg.pool == ""


def test_spawn_profile_pool_default():
    p = SpawnProfile()
    assert p.pool == ""


def test_spawn_profile_with_pool():
    p = SpawnProfile(system_prompt="You are a coder.", pool="fast")
    assert p.pool == "fast"


def test_settings_loads_from_json_file(tmp_path):
    config = {"llm": {"default_pool": "default"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))
    settings = Settings.load(config_file)
    assert settings.llm.default_pool == "default"


def test_matrix_channel_disabled_by_default():
    settings = Settings()
    assert settings.channels.matrix.enabled is False


def test_email_channel_disabled_by_default():
    settings = Settings()
    assert settings.channels.email.enabled is False


def test_mcp_server_config_stdio_defaults():
    from squidbot.config.schema import McpServerConfig

    cfg = McpServerConfig(command="uvx", args=["mcp-server-github"])
    assert cfg.transport == "stdio"
    assert cfg.command == "uvx"
    assert cfg.args == ["mcp-server-github"]
    assert cfg.env is None
    assert cfg.url == ""


def test_mcp_server_config_http():
    from squidbot.config.schema import McpServerConfig

    cfg = McpServerConfig(transport="http", url="http://localhost:8080/mcp")
    assert cfg.transport == "http"
    assert cfg.url == "http://localhost:8080/mcp"


def test_tools_config_mcp_servers_typed():
    from squidbot.config.schema import McpServerConfig, ToolsConfig

    cfg = ToolsConfig(mcp_servers={"github": {"command": "uvx", "args": ["mcp-server-github"]}})
    assert isinstance(cfg.mcp_servers["github"], McpServerConfig)


def test_spawn_settings_defaults():
    s = SpawnSettings()
    assert s.enabled is False
    assert s.profiles == {}


def test_spawn_profile_fields():
    p = SpawnProfile(system_prompt="You are a coder.", tools=["shell"])
    assert p.system_prompt == "You are a coder."
    assert p.tools == ["shell"]


def test_spawn_settings_in_tools_config():
    cfg = ToolsConfig()
    assert cfg.spawn.enabled is False


def test_spawn_profile_empty_tools_means_all():
    p = SpawnProfile()
    assert p.tools == []  # empty = inherit all


from pydantic import ValidationError  # noqa: E402


def test_validation_unknown_default_pool():
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "llm": {
                    "default_pool": "missing",
                    "providers": {"p": {"api_base": "http://x", "api_key": "k"}},
                    "models": {"m": {"provider": "p", "model": "x"}},
                    "pools": {"smart": [{"model": "m"}]},
                }
            }
        )


def test_validation_pool_references_unknown_model():
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "llm": {
                    "default_pool": "smart",
                    "providers": {"p": {"api_base": "http://x", "api_key": "k"}},
                    "models": {"m": {"provider": "p", "model": "x"}},
                    "pools": {"smart": [{"model": "ghost"}]},
                }
            }
        )


def test_validation_model_references_unknown_provider():
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "llm": {
                    "default_pool": "smart",
                    "providers": {},
                    "models": {"m": {"provider": "no_provider", "model": "x"}},
                    "pools": {"smart": [{"model": "m"}]},
                }
            }
        )


def test_validation_heartbeat_pool_unknown():
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "llm": {
                    "default_pool": "smart",
                    "providers": {"p": {"api_base": "http://x", "api_key": "k"}},
                    "models": {"m": {"provider": "p", "model": "x"}},
                    "pools": {"smart": [{"model": "m"}]},
                },
                "agents": {"heartbeat": {"pool": "missing"}},
            }
        )


def test_validation_spawn_profile_pool_unknown():
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "llm": {
                    "default_pool": "smart",
                    "providers": {"p": {"api_base": "http://x", "api_key": "k"}},
                    "models": {"m": {"provider": "p", "model": "x"}},
                    "pools": {"smart": [{"model": "m"}]},
                },
                "tools": {"spawn": {"profiles": {"researcher": {"pool": "missing"}}}},
            }
        )


def test_validation_empty_pools_is_valid():
    """Empty pools config (unconfigured) should not fail validation."""
    s = Settings.model_validate({})
    assert s.llm.pools == {}


def test_spawn_profile_bootstrap_files_default():
    profile = SpawnProfile()
    assert profile.bootstrap_files == []
    assert profile.system_prompt_file == ""


def test_spawn_profile_bootstrap_files_set():
    profile = SpawnProfile(bootstrap_files=["SOUL.md", "AGENTS.md"])
    assert profile.bootstrap_files == ["SOUL.md", "AGENTS.md"]


def test_spawn_profile_system_prompt_file():
    profile = SpawnProfile(system_prompt_file="RESEARCHER.md")
    assert profile.system_prompt_file == "RESEARCHER.md"


def test_agent_config_no_longer_has_system_prompt_file():
    cfg = AgentConfig()
    assert not hasattr(cfg, "system_prompt_file")
