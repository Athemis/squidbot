"""Tests for the skills system."""

from __future__ import annotations

import os

import pytest

from squidbot.adapters.skills.fs import FsSkillsLoader
from squidbot.core.skills import build_skills_xml


@pytest.fixture
def skill_dir(tmp_path):
    """Create a temporary skills directory with one skill."""
    skill = tmp_path / "github"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: github\n"
        'description: "Interact with GitHub."\n'
        "always: false\n"
        "requires:\n"
        "  bins: []\n"
        "---\n\n# GitHub Skill\n\nDo stuff with GitHub.\n"
    )
    return tmp_path


def test_list_skills_discovers_skill(skill_dir):
    loader = FsSkillsLoader(search_dirs=[skill_dir])
    skills = loader.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "github"
    assert "GitHub" in skills[0].description


def test_load_skill_body(skill_dir):
    loader = FsSkillsLoader(search_dirs=[skill_dir])
    body = loader.load_skill_body("github")
    assert "GitHub Skill" in body


def test_mtime_cache(skill_dir):
    loader = FsSkillsLoader(search_dirs=[skill_dir])
    skills1 = loader.list_skills()
    skills2 = loader.list_skills()
    # Second call uses cache — same objects
    assert skills1[0].name == skills2[0].name


def test_higher_priority_dir_shadows_lower(tmp_path):
    low = tmp_path / "low"
    high = tmp_path / "high"
    for d in (low, high):
        skill = d / "github"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: github\ndescription: 'From {d.name}'\n---\n")
    loader = FsSkillsLoader(search_dirs=[high, low])
    skills = loader.list_skills()
    assert len(skills) == 1
    assert "high" in skills[0].description


def test_always_skill_excluded_from_xml(skill_dir):
    (skill_dir / "memory").mkdir()
    (skill_dir / "memory" / "SKILL.md").write_text(
        "---\nname: memory\ndescription: 'Memory'\nalways: true\n---\n"
    )
    loader = FsSkillsLoader(search_dirs=[skill_dir])
    skills = loader.list_skills()
    xml = build_skills_xml(skills)
    assert "memory" not in xml  # always-skill excluded from XML listing
    assert "github" in xml


def test_unavailable_skill_shows_requires(tmp_path):
    skill = tmp_path / "gh-tool"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: gh-tool\ndescription: 'Needs gh'\nrequires:\n"
        "  bins: [__nonexistent_bin__]\n---\n"
    )
    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()
    assert skills[0].available is False
    xml = build_skills_xml(skills)
    assert 'available="false"' in xml


def test_list_skills_ttl_cache_hit_skips_scan_work(skill_dir, monkeypatch):
    loader = FsSkillsLoader(search_dirs=[skill_dir])
    root_iterdir_calls = 0
    skill_stat_calls = 0
    original_iterdir = type(skill_dir).iterdir
    original_stat = type(skill_dir).stat
    monotonic_values = iter([100.0, 101.0])

    def tracked_iterdir(path_obj):
        nonlocal root_iterdir_calls
        if path_obj == skill_dir:
            root_iterdir_calls += 1
        return original_iterdir(path_obj)

    def tracked_stat(path_obj, *args, **kwargs):
        nonlocal skill_stat_calls
        if path_obj == skill_dir / "github" / "SKILL.md":
            skill_stat_calls += 1
        return original_stat(path_obj, *args, **kwargs)

    monkeypatch.setattr(type(skill_dir), "iterdir", tracked_iterdir)
    monkeypatch.setattr(type(skill_dir), "stat", tracked_stat)
    monkeypatch.setattr(
        "squidbot.adapters.skills.fs.time.monotonic", lambda: next(monotonic_values)
    )

    loader.list_skills()
    first_iterdir_calls = root_iterdir_calls
    first_stat_calls = skill_stat_calls
    loader.list_skills()

    assert root_iterdir_calls == first_iterdir_calls
    assert skill_stat_calls == first_stat_calls


def test_load_skill_body_uses_mtime_cache(skill_dir, monkeypatch):
    loader = FsSkillsLoader(search_dirs=[skill_dir])
    skill_file = skill_dir / "github" / "SKILL.md"
    read_text_calls = 0
    original_read_text = type(skill_file).read_text

    def tracked_read_text(path_obj, *args, **kwargs):
        nonlocal read_text_calls
        if path_obj == skill_file:
            read_text_calls += 1
        return original_read_text(path_obj, *args, **kwargs)

    monkeypatch.setattr(type(skill_file), "read_text", tracked_read_text)

    first_body = loader.load_skill_body("github")
    second_body = loader.load_skill_body("github")

    assert first_body == second_body
    assert read_text_calls == 1


def test_touching_skill_file_invalidates_list_and_body_cache(skill_dir, monkeypatch):
    loader = FsSkillsLoader(search_dirs=[skill_dir])
    skill_file = skill_dir / "github" / "SKILL.md"
    monotonic_values = iter([50.0, 53.0])
    monkeypatch.setattr(
        "squidbot.adapters.skills.fs.time.monotonic", lambda: next(monotonic_values)
    )

    original_skills = loader.list_skills()
    original_body = loader.load_skill_body("github")

    skill_file.write_text(
        "---\n"
        "name: github\n"
        'description: "Updated description"\n'
        "always: false\n"
        "requires:\n"
        "  bins: []\n"
        "---\n\n# GitHub Skill\n\nUpdated body.\n",
        encoding="utf-8",
    )
    current_mtime = skill_file.stat().st_mtime
    os.utime(skill_file, (current_mtime + 1, current_mtime + 1))

    refreshed_skills = loader.list_skills()
    refreshed_body = loader.load_skill_body("github")

    assert original_skills[0].description != refreshed_skills[0].description
    assert "Updated description" in refreshed_skills[0].description
    assert original_body != refreshed_body
    assert "Updated body." in refreshed_body
