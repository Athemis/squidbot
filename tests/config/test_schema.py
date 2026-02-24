"""Tests for OwnerAliasEntry and OwnerConfig config schema classes."""

from __future__ import annotations

import json
import pathlib

from squidbot.config.schema import OwnerAliasEntry, OwnerConfig, Settings


def test_owner_alias_entry_string_form() -> None:
    # plain string alias — matches all channels
    entry = OwnerAliasEntry(address="alex")
    assert entry.address == "alex"
    assert entry.channel is None


def test_owner_alias_entry_scoped() -> None:
    entry = OwnerAliasEntry(address="alex@example.com", channel="email")
    assert entry.channel == "email"


def test_owner_config_defaults_empty() -> None:
    cfg = OwnerConfig()
    assert cfg.aliases == []


def test_settings_has_owner_field() -> None:
    s = Settings()
    assert isinstance(s.owner, OwnerConfig)


def test_settings_load_owner_aliases(tmp_path: pathlib.Path) -> None:
    data = {
        "owner": {
            "aliases": [
                "alex",
                {"address": "@alex:matrix.org", "channel": "matrix"},
            ]
        }
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    s = Settings.load(path)
    assert len(s.owner.aliases) == 2
    assert s.owner.aliases[0].address == "alex"
    assert s.owner.aliases[1].channel == "matrix"


def test_owner_alias_entry_from_value_string() -> None:
    entry = OwnerAliasEntry.from_value("alex")
    assert entry.address == "alex"
    assert entry.channel is None


def test_owner_alias_entry_from_value_dict() -> None:
    entry = OwnerAliasEntry.from_value({"address": "@alex:matrix.org", "channel": "matrix"})
    assert entry.address == "@alex:matrix.org"
    assert entry.channel == "matrix"


def test_owner_config_model_validate_coerces_aliases() -> None:
    cfg = OwnerConfig.model_validate(
        {"aliases": ["alex", {"address": "@alex:matrix.org", "channel": "matrix"}]}
    )
    assert len(cfg.aliases) == 2
    assert cfg.aliases[0].address == "alex"
    assert cfg.aliases[1].channel == "matrix"


def test_owner_config_model_validate_empty_aliases() -> None:
    cfg = OwnerConfig.model_validate({"aliases": []})
    assert cfg.aliases == []
