"""Tests for OwnerAliasEntry and OwnerConfig config schema classes."""

from __future__ import annotations

import json
import pathlib
import tempfile

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


def test_settings_load_owner_aliases() -> None:
    data = {
        "owner": {
            "aliases": [
                "alex",
                {"address": "@alex:matrix.org", "channel": "matrix"},
            ]
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = pathlib.Path(f.name)
    s = Settings.load(path)
    assert len(s.owner.aliases) == 2
    assert s.owner.aliases[0].address == "alex"
    assert s.owner.aliases[1].channel == "matrix"
    path.unlink()
