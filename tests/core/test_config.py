import json

from squidbot.config.schema import (
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
