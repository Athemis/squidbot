"""Tests for the skills system."""

from __future__ import annotations

import pytest
from pathlib import Path
from squidbot.core.skills import SkillMetadata, build_skills_xml
from squidbot.adapters.skills.fs import FsSkillsLoader


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
        "---\nname: gh-tool\ndescription: 'Needs gh'\nrequires:\n  bins: [__nonexistent_bin__]\n---\n"
    )
    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()
    assert skills[0].available is False
    xml = build_skills_xml(skills)
    assert 'available="false"' in xml
