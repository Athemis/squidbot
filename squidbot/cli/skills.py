"""Skills subcommands for squidbot CLI.

Provides commands to inspect discovered skills.
"""

from __future__ import annotations

from pathlib import Path

import cyclopts

from squidbot.config.schema import DEFAULT_CONFIG_PATH, Settings

skills_app = cyclopts.App(name="skills", help="Manage squidbot skills.")


@skills_app.command
def list_skills(config: Path = DEFAULT_CONFIG_PATH) -> None:
    """List all discovered skills and their availability."""
    from squidbot.adapters.skills.fs import FsSkillsLoader

    settings = Settings.load(config)
    workspace = Path(settings.agents.workspace).expanduser()
    bundled = Path(__file__).parent.parent / "skills"

    extra_dirs = [Path(d).expanduser() for d in settings.skills.extra_dirs]
    search_dirs = extra_dirs + [workspace / "skills", bundled]

    loader = FsSkillsLoader(search_dirs=search_dirs)
    skills = loader.list_skills()

    if not skills:
        print("No skills found.")
        return

    for skill in sorted(skills, key=lambda s: s.name):
        avail = "+" if skill.available else "-"
        always = " [always]" if skill.always else ""
        print(f"  [{avail}] {skill.name}{always}")
        print(f"       {skill.description}")
        if not skill.available:
            if skill.requires_bins:
                print(f"       missing bins: {', '.join(skill.requires_bins)}")
            if skill.requires_env:
                print(f"       missing env:  {', '.join(skill.requires_env)}")
