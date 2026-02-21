"""
Skills metadata model and XML summary builder.

The core domain only knows about SkillMetadata and the XML block format.
All filesystem I/O lives in the FsSkillsLoader adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring


@dataclass
class SkillMetadata:
    """Parsed metadata from a SKILL.md frontmatter block."""

    name: str
    description: str
    location: Path  # absolute path to SKILL.md
    always: bool = False  # inject full body into every system prompt
    available: bool = True  # False if required bins/env are missing
    requires_bins: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)
    emoji: str = ""


def build_skills_xml(skills: list[SkillMetadata]) -> str:
    """
    Build the <skills> XML block injected into the system prompt.

    Always-skills are excluded here — their full body is injected directly.
    """
    root = Element("skills")
    for skill in skills:
        if skill.always:
            continue  # injected as full body, not listed in XML
        el = SubElement(root, "skill", available=str(skill.available).lower())
        SubElement(el, "name").text = skill.name
        SubElement(el, "description").text = skill.description
        SubElement(el, "location").text = str(skill.location)
        if not skill.available:
            hints = []
            if skill.requires_bins:
                hints.append(f"CLI: {', '.join(skill.requires_bins)}")
            if skill.requires_env:
                hints.append(f"env: {', '.join(skill.requires_env)}")
            SubElement(el, "requires").text = "; ".join(hints)
    return tostring(root, encoding="unicode")
