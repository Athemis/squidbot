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
