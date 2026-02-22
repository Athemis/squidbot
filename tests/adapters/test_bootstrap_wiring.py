from __future__ import annotations

from pathlib import Path

from squidbot.cli.main import BOOTSTRAP_FILES_MAIN, BOOTSTRAP_FILES_SUBAGENT, _load_bootstrap_prompt


def test_load_bootstrap_prompt_all_present(tmp_path: Path) -> None:
    (tmp_path / "SOUL.md").write_text("soul content")
    (tmp_path / "AGENTS.md").write_text("agents content")
    result = _load_bootstrap_prompt(tmp_path, ["SOUL.md", "AGENTS.md"])
    assert "soul content" in result
    assert "agents content" in result


def test_load_bootstrap_prompt_missing_files_skipped(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("agents content")
    result = _load_bootstrap_prompt(tmp_path, ["SOUL.md", "AGENTS.md"])
    assert "agents content" in result
    assert "soul" not in result.lower()


def test_load_bootstrap_prompt_all_missing_returns_fallback(tmp_path: Path) -> None:
    result = _load_bootstrap_prompt(tmp_path, ["SOUL.md", "AGENTS.md"])
    assert result == "You are a helpful personal AI assistant."


def test_load_bootstrap_prompt_separator(tmp_path: Path) -> None:
    (tmp_path / "SOUL.md").write_text("soul")
    (tmp_path / "AGENTS.md").write_text("agents")
    result = _load_bootstrap_prompt(tmp_path, ["SOUL.md", "AGENTS.md"])
    assert "\n\n---\n\n" in result


def test_load_bootstrap_prompt_empty_filenames_returns_fallback(tmp_path: Path) -> None:
    result = _load_bootstrap_prompt(tmp_path, [])
    assert result == "You are a helpful personal AI assistant."


def test_bootstrap_files_main_order() -> None:
    assert BOOTSTRAP_FILES_MAIN == [
        "IDENTITY.md",
        "SOUL.md",
        "USER.md",
        "AGENTS.md",
        "ENVIRONMENT.md",
    ]


def test_bootstrap_files_subagent() -> None:
    assert BOOTSTRAP_FILES_SUBAGENT == ["AGENTS.md", "ENVIRONMENT.md"]
