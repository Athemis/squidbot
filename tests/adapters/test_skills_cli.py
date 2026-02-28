"""Tests for squidbot.cli.skills.list_skills() output formatting."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from _pytest.capture import CaptureFixture

from squidbot.cli.skills import list_skills
from squidbot.config.schema import Settings
from squidbot.core.skills import SkillMetadata


def test_list_skills_no_skills(capsys: CaptureFixture[str]) -> None:
    """No skills found → prints 'No skills found.'"""
    settings = Settings()
    settings.agents.workspace = "/tmp/workspace"
    settings.skills.extra_dirs = []

    with (
        patch("squidbot.cli.skills.Settings.load", return_value=settings),
        patch("squidbot.adapters.skills.fs.FsSkillsLoader") as mock_loader_class,
    ):
        mock_loader = mock_loader_class.return_value
        mock_loader.list_skills.return_value = []

        list_skills(Path("/tmp/config.yaml"))

    captured = capsys.readouterr()
    assert "No skills found." in captured.out


def test_list_skills_sorted_by_name(capsys: CaptureFixture[str]) -> None:
    """Skills are sorted by name."""
    settings = Settings()
    settings.agents.workspace = "/tmp/workspace"
    settings.skills.extra_dirs = []

    skills = [
        SkillMetadata(
            name="zebra",
            description="Last alphabetically",
            location=Path("/tmp/zebra/SKILL.md"),
            available=True,
        ),
        SkillMetadata(
            name="apple",
            description="First alphabetically",
            location=Path("/tmp/apple/SKILL.md"),
            available=True,
        ),
        SkillMetadata(
            name="middle",
            description="Middle alphabetically",
            location=Path("/tmp/middle/SKILL.md"),
            available=True,
        ),
    ]

    with (
        patch("squidbot.cli.skills.Settings.load", return_value=settings),
        patch("squidbot.adapters.skills.fs.FsSkillsLoader") as mock_loader_class,
    ):
        mock_loader = mock_loader_class.return_value
        mock_loader.list_skills.return_value = skills

        list_skills(Path("/tmp/config.yaml"))

    captured = capsys.readouterr()
    lines = captured.out.split("\n")
    # Find the lines with skill names
    skill_lines = [line for line in lines if "[+]" in line or "[-]" in line]
    assert len(skill_lines) == 3
    assert "apple" in skill_lines[0]
    assert "middle" in skill_lines[1]
    assert "zebra" in skill_lines[2]


def test_list_skills_available_skill(capsys: CaptureFixture[str]) -> None:
    """Available skill prints [+] and description."""
    settings = Settings()
    settings.agents.workspace = "/tmp/workspace"
    settings.skills.extra_dirs = []

    skills = [
        SkillMetadata(
            name="test_skill",
            description="A test skill",
            location=Path("/tmp/test_skill/SKILL.md"),
            available=True,
        ),
    ]

    with (
        patch("squidbot.cli.skills.Settings.load", return_value=settings),
        patch("squidbot.adapters.skills.fs.FsSkillsLoader") as mock_loader_class,
    ):
        mock_loader = mock_loader_class.return_value
        mock_loader.list_skills.return_value = skills

        list_skills(Path("/tmp/config.yaml"))

    captured = capsys.readouterr()
    assert "[+] test_skill" in captured.out
    assert "A test skill" in captured.out


def test_list_skills_unavailable_skill_missing_bins(capsys: CaptureFixture[str]) -> None:
    """Unavailable skill prints [-] with missing bins line."""
    settings = Settings()
    settings.agents.workspace = "/tmp/workspace"
    settings.skills.extra_dirs = []

    skills = [
        SkillMetadata(
            name="test_skill",
            description="A test skill",
            location=Path("/tmp/test_skill/SKILL.md"),
            available=False,
            requires_bins=["missing_bin", "another_bin"],
        ),
    ]

    with (
        patch("squidbot.cli.skills.Settings.load", return_value=settings),
        patch("squidbot.adapters.skills.fs.FsSkillsLoader") as mock_loader_class,
    ):
        mock_loader = mock_loader_class.return_value
        mock_loader.list_skills.return_value = skills

        list_skills(Path("/tmp/config.yaml"))

    captured = capsys.readouterr()
    assert "[-] test_skill" in captured.out
    assert "missing bins: missing_bin, another_bin" in captured.out


def test_list_skills_unavailable_skill_missing_env(capsys: CaptureFixture[str]) -> None:
    """Unavailable skill prints [-] with missing env line."""
    settings = Settings()
    settings.agents.workspace = "/tmp/workspace"
    settings.skills.extra_dirs = []

    skills = [
        SkillMetadata(
            name="test_skill",
            description="A test skill",
            location=Path("/tmp/test_skill/SKILL.md"),
            available=False,
            requires_env=["MISSING_VAR", "ANOTHER_VAR"],
        ),
    ]

    with (
        patch("squidbot.cli.skills.Settings.load", return_value=settings),
        patch("squidbot.adapters.skills.fs.FsSkillsLoader") as mock_loader_class,
    ):
        mock_loader = mock_loader_class.return_value
        mock_loader.list_skills.return_value = skills

        list_skills(Path("/tmp/config.yaml"))

    captured = capsys.readouterr()
    assert "[-] test_skill" in captured.out
    assert "missing env:  MISSING_VAR, ANOTHER_VAR" in captured.out


def test_list_skills_unavailable_skill_both_missing(capsys: CaptureFixture[str]) -> None:
    """Unavailable skill with both missing bins and env prints both lines."""
    settings = Settings()
    settings.agents.workspace = "/tmp/workspace"
    settings.skills.extra_dirs = []

    skills = [
        SkillMetadata(
            name="test_skill",
            description="A test skill",
            location=Path("/tmp/test_skill/SKILL.md"),
            available=False,
            requires_bins=["missing_bin"],
            requires_env=["MISSING_VAR"],
        ),
    ]

    with (
        patch("squidbot.cli.skills.Settings.load", return_value=settings),
        patch("squidbot.adapters.skills.fs.FsSkillsLoader") as mock_loader_class,
    ):
        mock_loader = mock_loader_class.return_value
        mock_loader.list_skills.return_value = skills

        list_skills(Path("/tmp/config.yaml"))

    captured = capsys.readouterr()
    assert "[-] test_skill" in captured.out
    assert "missing bins: missing_bin" in captured.out
    assert "missing env:  MISSING_VAR" in captured.out


def test_list_skills_always_skill(capsys: CaptureFixture[str]) -> None:
    """Always skill prints [always] marker."""
    settings = Settings()
    settings.agents.workspace = "/tmp/workspace"
    settings.skills.extra_dirs = []

    skills = [
        SkillMetadata(
            name="always_skill",
            description="An always skill",
            location=Path("/tmp/always_skill/SKILL.md"),
            available=True,
            always=True,
        ),
    ]

    with (
        patch("squidbot.cli.skills.Settings.load", return_value=settings),
        patch("squidbot.adapters.skills.fs.FsSkillsLoader") as mock_loader_class,
    ):
        mock_loader = mock_loader_class.return_value
        mock_loader.list_skills.return_value = skills

        list_skills(Path("/tmp/config.yaml"))

    captured = capsys.readouterr()
    assert "[+] always_skill [always]" in captured.out
    assert "An always skill" in captured.out


def test_list_skills_mixed_skills(capsys: CaptureFixture[str]) -> None:
    """Mixed skills with various states are formatted correctly."""
    settings = Settings()
    settings.agents.workspace = "/tmp/workspace"
    settings.skills.extra_dirs = []

    skills = [
        SkillMetadata(
            name="available",
            description="Available skill",
            location=Path("/tmp/available/SKILL.md"),
            available=True,
        ),
        SkillMetadata(
            name="always",
            description="Always skill",
            location=Path("/tmp/always/SKILL.md"),
            available=True,
            always=True,
        ),
        SkillMetadata(
            name="unavailable",
            description="Unavailable skill",
            location=Path("/tmp/unavailable/SKILL.md"),
            available=False,
            requires_bins=["missing"],
        ),
    ]

    with (
        patch("squidbot.cli.skills.Settings.load", return_value=settings),
        patch("squidbot.adapters.skills.fs.FsSkillsLoader") as mock_loader_class,
    ):
        mock_loader = mock_loader_class.return_value
        mock_loader.list_skills.return_value = skills

        list_skills(Path("/tmp/config.yaml"))

    captured = capsys.readouterr()
    # Check all skills are present
    assert "[+] always [always]" in captured.out
    assert "[+] available" in captured.out
    assert "[-] unavailable" in captured.out
    # Check descriptions
    assert "Always skill" in captured.out
    assert "Available skill" in captured.out
    assert "Unavailable skill" in captured.out
    # Check missing bins line
    assert "missing bins: missing" in captured.out


def test_list_skills_uses_configured_workspace(capsys: CaptureFixture[str]) -> None:
    """list_skills uses workspace from settings."""
    settings = Settings()
    settings.agents.workspace = "/custom/workspace"
    settings.skills.extra_dirs = []

    with (
        patch("squidbot.cli.skills.Settings.load", return_value=settings),
        patch("squidbot.adapters.skills.fs.FsSkillsLoader") as mock_loader_class,
    ):
        mock_loader = mock_loader_class.return_value
        mock_loader.list_skills.return_value = []

        list_skills(Path("/tmp/config.yaml"))

        # Verify FsSkillsLoader was called with correct search_dirs
        call_args = mock_loader_class.call_args
        search_dirs = call_args[1]["search_dirs"]
        # Should include workspace/skills
        assert any("/custom/workspace/skills" in str(d) for d in search_dirs)


def test_list_skills_uses_extra_dirs(capsys: CaptureFixture[str]) -> None:
    """list_skills includes extra_dirs from settings."""
    settings = Settings()
    settings.agents.workspace = "/workspace"
    settings.skills.extra_dirs = ["/extra1", "/extra2"]

    with (
        patch("squidbot.cli.skills.Settings.load", return_value=settings),
        patch("squidbot.adapters.skills.fs.FsSkillsLoader") as mock_loader_class,
    ):
        mock_loader = mock_loader_class.return_value
        mock_loader.list_skills.return_value = []

        list_skills(Path("/tmp/config.yaml"))

        # Verify FsSkillsLoader was called with extra_dirs first
        call_args = mock_loader_class.call_args
        search_dirs = call_args[1]["search_dirs"]
        search_dirs_str = [str(d) for d in search_dirs]
        # Extra dirs should come first
        assert "/extra1" in search_dirs_str
        assert "/extra2" in search_dirs_str
        assert search_dirs_str.index("/extra1") < search_dirs_str.index("/workspace/skills")
