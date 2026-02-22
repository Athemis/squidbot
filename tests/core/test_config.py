import json

from squidbot.config.schema import LLMConfig, Settings


def test_default_llm_config():
    cfg = LLMConfig()
    assert cfg.model == "anthropic/claude-opus-4-5"
    assert cfg.max_tokens == 8192
    assert cfg.max_context_tokens == 100_000


def test_settings_from_dict():
    raw = {
        "llm": {
            "api_base": "https://openrouter.ai/api/v1",
            "api_key": "sk-test",
            "model": "openai/gpt-4o",
        }
    }
    settings = Settings.model_validate(raw)
    assert settings.llm.api_key == "sk-test"
    assert settings.llm.model == "openai/gpt-4o"


def test_settings_loads_from_json_file(tmp_path):
    config = {"llm": {"api_key": "sk-from-file"}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))
    settings = Settings.load(config_file)
    assert settings.llm.api_key == "sk-from-file"


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
