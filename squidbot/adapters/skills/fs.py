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
import time
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
        self._body_cache: dict[tuple[Path, float], str] = {}
        self._list_cache_ttl_seconds = 2.0
        self._list_cache_timestamp: float | None = None
        self._list_cache: tuple[SkillMetadata, ...] | None = None

    def list_skills(self) -> list[SkillMetadata]:
        """
        Return all discovered skills, with higher-priority dirs shadowing lower ones.

        Skills are re-read from disk only if their mtime has changed.
        """
        now = time.monotonic()
        if (
            self._list_cache is not None
            and self._list_cache_timestamp is not None
            and now - self._list_cache_timestamp < self._list_cache_ttl_seconds
        ):
            return list(self._list_cache)

        seen: dict[str, SkillMetadata] = {}  # name → metadata (first-wins = highest priority)
        discovered_paths: set[Path] = set()

        for search_dir in self._search_dirs:
            if not search_dir.is_dir():
                continue
            for skill_dir in sorted(search_dir.iterdir()):
                skill_file = skill_dir / "SKILL.md"
                if not skill_dir.is_dir() or not skill_file.exists():
                    continue
                discovered_paths.add(skill_file)
                name = skill_dir.name
                if name in seen:
                    continue  # already shadowed by higher-priority dir
                metadata = self._load_cached(skill_file, name)
                if metadata:
                    seen[name] = metadata

        stale_paths = [path for path in self._cache if path not in discovered_paths]
        for stale_path in stale_paths:
            del self._cache[stale_path]
            self._clear_body_cache_for_path(stale_path)

        self._list_cache = tuple(seen.values())
        self._list_cache_timestamp = now

        return list(self._list_cache)

    def load_skill_body(self, name: str) -> str:
        """Return the full SKILL.md text for a named skill."""
        for search_dir in self._search_dirs:
            skill_file = search_dir / name / "SKILL.md"
            if skill_file.exists():
                mtime = skill_file.stat().st_mtime
                cache_key = (skill_file, mtime)
                if cache_key in self._body_cache:
                    return self._body_cache[cache_key]

                self._clear_body_cache_for_path(skill_file)
                body = skill_file.read_text(encoding="utf-8")
                self._body_cache[cache_key] = body
                return body
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

    def _clear_body_cache_for_path(self, path: Path) -> None:
        stale_keys = [key for key in self._body_cache if key[0] == path]
        for stale_key in stale_keys:
            del self._body_cache[stale_key]
