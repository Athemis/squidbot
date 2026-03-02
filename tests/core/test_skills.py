"""Tests for the skills system."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from squidbot.adapters.skills.loader import FsSkillsLoader
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


def test_bundled_tmux_skill_is_discoverable():
    bundled_skills = Path(__file__).parents[2] / "squidbot" / "skills"
    loader = FsSkillsLoader(search_dirs=[bundled_skills])

    skills = loader.list_skills()
    tmux_skill = next((skill for skill in skills if skill.name == "tmux"), None)

    assert tmux_skill is not None
    assert tmux_skill.description
    body = loader.load_skill_body("tmux")
    assert "bins: [tmux]" in body


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


def test_openclaw_requires_fallback_marks_skill_unavailable(tmp_path):
    skill = tmp_path / "tmux"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: tmux\n"
        "description: 'tmux skill'\n"
        "metadata:\n"
        "  openclaw:\n"
        "    requires:\n"
        "      bins: [__definitely_missing_tmux_bin__]\n"
        "---\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert skills[0].available is False
    assert "__definitely_missing_tmux_bin__" in skills[0].requires_bins


def test_frontmatter_parsing_ignores_triple_dash_inside_yaml_string(tmp_path):
    skill = tmp_path / "dashy"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        '---\nname: dashy\ndescription: "contains --- inside"\n---\n# Dashy Skill\n',
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "dashy"
    assert "contains --- inside" in skills[0].description


def test_frontmatter_parsing_ignores_indented_triple_dash_in_block_scalar(tmp_path):
    skill = tmp_path / "blocky"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: blocky\n"
        "description: |\n"
        "  first line\n"
        "  ---\n"
        "  last line\n"
        "---\n"
        "# Blocky Skill\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "blocky"
    assert "first line" in skills[0].description
    assert "last line" in skills[0].description


def test_frontmatter_without_closing_delimiter_returns_no_metadata(tmp_path):
    skill = tmp_path / "broken"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: broken\ndescription: missing closer\n# body without closing delimiter\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "broken"
    assert skills[0].description == ""


def test_frontmatter_without_opening_delimiter_uses_fallback_defaults(tmp_path):
    skill = tmp_path / "plain"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "name: plain\ndescription: not-frontmatter\n# Plain Skill\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "plain"
    assert skills[0].description == ""


def test_malformed_frontmatter_yaml_is_skipped_without_crash(tmp_path):
    skill = tmp_path / "badyaml"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        '---\nname: badyaml\ndescription: "unterminated\n---\n',
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert skills == []


def test_frontmatter_with_leading_whitespace_opening_fence_uses_fallback_defaults(tmp_path):
    skill = tmp_path / "ws-open"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        " ---\nname: ws-open\ndescription: should not parse\n---\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "ws-open"
    assert skills[0].description == ""


def test_frontmatter_with_trailing_space_opening_fence_uses_fallback_defaults(tmp_path):
    skill = tmp_path / "space-open"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "--- \nname: space-open\ndescription: should not parse\n---\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "space-open"
    assert skills[0].description == ""


def test_frontmatter_with_trailing_space_closing_fence_uses_fallback_defaults(tmp_path):
    skill = tmp_path / "space-close"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: space-close\ndescription: should not parse\n--- \n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "space-close"
    assert skills[0].description == ""


def test_frontmatter_with_bom_prefixed_opening_fence_is_not_treated_as_delimiter(tmp_path):
    skill = tmp_path / "bom-open"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "\ufeff---\nname: bom-open\ndescription: should not parse\n---\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "bom-open"
    assert skills[0].description == ""


def test_frontmatter_with_crlf_fences_parses_metadata(tmp_path):
    skill = tmp_path / "crlf"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        '---\r\nname: crlf\r\ndescription: "crlf delimiters"\r\n---\r\n# CRLF Skill\r\n',
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "crlf"
    assert "crlf delimiters" in skills[0].description


def test_frontmatter_preserves_block_scalar_boundary_blank_lines(tmp_path):
    skill = tmp_path / "boundary"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: boundary\ndescription: |\n\n  line\n\n---\n# Boundary Skill\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "boundary"
    assert skills[0].description == "\nline\n"


def test_top_level_requires_precedence_over_openclaw(tmp_path):
    skill = tmp_path / "tmux"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: tmux\n"
        "description: 'tmux skill'\n"
        "requires:\n"
        "  bins: []\n"
        "metadata:\n"
        "  openclaw:\n"
        "    requires:\n"
        "      bins: [__definitely_missing_tmux_bin__]\n"
        "---\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert skills[0].available is True
    assert skills[0].requires_bins == []


def test_openclaw_requires_used_when_top_level_requires_is_empty_dict(tmp_path):
    skill = tmp_path / "tmux"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: tmux\n"
        "description: 'tmux skill'\n"
        "requires: {}\n"
        "metadata:\n"
        "  openclaw:\n"
        "    requires:\n"
        "      bins: [__definitely_missing_tmux_bin__]\n"
        "---\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert skills[0].available is False
    assert "__definitely_missing_tmux_bin__" in skills[0].requires_bins


def test_invalid_requires_shapes_do_not_crash(tmp_path):
    skill = tmp_path / "tmux"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: tmux\n"
        "description: 'tmux skill'\n"
        "requires: definitely-not-a-dict\n"
        "metadata:\n"
        "  openclaw:\n"
        "    requires:\n"
        "      bins: definitely-not-a-list\n"
        "      env: {NOT: A_LIST}\n"
        "---\n",
        encoding="utf-8",
    )

    loader = FsSkillsLoader(search_dirs=[tmp_path])
    skills = loader.list_skills()

    assert len(skills) == 1
    assert skills[0].available is True
    assert skills[0].requires_bins == []
    assert skills[0].requires_env == []


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
        "squidbot.adapters.skills.loader.time.monotonic", lambda: next(monotonic_values)
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
        "squidbot.adapters.skills.loader.time.monotonic", lambda: next(monotonic_values)
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
