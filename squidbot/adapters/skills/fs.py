"""
Filesystem-based skills loader with mtime-based cache invalidation.

Searches skill directories in priority order:
  1. Extra dirs from config (highest priority)
  2. Workspace skills directory
  3. Bundled package skills (lowest priority)

Skills with the same name in a higher-priority directory shadow lower ones.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from squidbot.core.skills import SkillMetadata

_yaml = YAML()
_yaml.preserve_quotes = True


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    """Extract YAML frontmatter from a SKILL.md file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    yaml_block = text[3:end].strip()
    data = _yaml.load(yaml_block)
    return dict(data) if data else {}


def _check_availability(meta: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """
    Check whether a skill's requirements are satisfied.

    Returns (available, missing_bins, missing_env).
    """
    requires = meta.get("requires", {}) or {}
    bins = requires.get("bins", []) or []
    envs = requires.get("env", []) or []

    missing_bins = [b for b in bins if shutil.which(b) is None]
    missing_env = [e for e in envs if not os.environ.get(e)]

    available = not missing_bins and not missing_env
    return available, missing_bins, missing_env


class FsSkillsLoader:
    """
    Loads and caches skill metadata from SKILL.md files on the filesystem.

    Cache invalidation is mtime-based: if a SKILL.md's modification time
    changes, its entry is reloaded on the next list_skills() call.
    """

    def __init__(self, search_dirs: list[Path]) -> None:
        """
        Args:
            search_dirs: Ordered list of directories to search for skills.
                         Earlier entries take precedence over later ones.
        """
        self._search_dirs = search_dirs
        # Cache: path → (mtime, SkillMetadata)
        self._cache: dict[Path, tuple[float, SkillMetadata]] = {}

    def list_skills(self) -> list[SkillMetadata]:
        """
        Return all discovered skills, with higher-priority dirs shadowing lower ones.

        Skills are re-read from disk only if their mtime has changed.
        """
        seen: dict[str, SkillMetadata] = {}  # name → metadata (first-wins = highest priority)

        for search_dir in self._search_dirs:
            if not search_dir.is_dir():
                continue
            for skill_dir in sorted(search_dir.iterdir()):
                skill_file = skill_dir / "SKILL.md"
                if not skill_dir.is_dir() or not skill_file.exists():
                    continue
                name = skill_dir.name
                if name in seen:
                    continue  # already shadowed by higher-priority dir
                metadata = self._load_cached(skill_file, name)
                if metadata:
                    seen[name] = metadata

        return list(seen.values())

    def load_skill_body(self, name: str) -> str:
        """Return the full SKILL.md text for a named skill."""
        for search_dir in self._search_dirs:
            skill_file = search_dir / name / "SKILL.md"
            if skill_file.exists():
                return skill_file.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Skill '{name}' not found")

    def _load_cached(self, path: Path, name: str) -> SkillMetadata | None:
        """Load metadata from cache, re-reading from disk if mtime changed."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None

        if path in self._cache:
            cached_mtime, cached_meta = self._cache[path]
            if cached_mtime == mtime:
                return cached_meta

        # Cache miss or stale — parse from disk
        try:
            meta = _parse_frontmatter(path)
        except Exception:
            return None

        available, missing_bins, missing_env = _check_availability(meta)
        squidbot_meta = (meta.get("metadata") or {}).get("squidbot", {}) or {}

        skill = SkillMetadata(
            name=meta.get("name", name),
            description=meta.get("description", ""),
            location=path,
            always=bool(meta.get("always", False)),
            available=available,
            requires_bins=missing_bins,
            requires_env=missing_env,
            emoji=squidbot_meta.get("emoji", ""),
        )
        self._cache[path] = (mtime, skill)
        return skill
