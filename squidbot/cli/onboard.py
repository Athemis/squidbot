"""Onboarding wizard for squidbot setup.

This module contains the interactive setup wizard that guides users through
initial configuration, including LLM settings, workspace creation, and
bootstrap file management.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from squidbot.config.schema import Settings

_BUNDLED_WORKSPACE = Path(__file__).parent.parent / "workspace"


def _load_or_init_settings(config_path: Path) -> Settings:
    """Load settings from disk or return default settings."""
    from squidbot.config.schema import Settings

    if config_path.exists():
        return Settings.load(config_path)
    return Settings()


def _prompt_llm_settings(settings: Settings) -> None:
    """Prompt for default LLM provider/model values and apply them."""
    from squidbot.config.schema import (  # noqa: PLC0415
        LLMModelConfig,
        LLMPoolEntry,
        LLMProviderConfig,
    )

    existing = settings.llm.providers.get("default")
    existing_model = settings.llm.models.get("default")

    default_api_base = (existing.api_base if existing else None) or "https://openrouter.ai/api/v1"
    default_api_key = (existing.api_key if existing else None) or ""
    default_model = (
        existing_model.model if existing_model else None
    ) or "anthropic/claude-opus-4-5"

    print("squidbot setup wizard")
    print("=" * 40)
    api_base = input(f"LLM API base URL [{default_api_base}]: ").strip() or default_api_base
    api_key_input = input(f"API key [{'*' * min(len(default_api_key), 8) or 'not set'}]: ").strip()
    api_key = api_key_input or default_api_key
    model_id = input(f"Model identifier [{default_model}]: ").strip() or default_model

    settings.llm.providers["default"] = LLMProviderConfig(api_base=api_base, api_key=api_key)
    settings.llm.models["default"] = LLMModelConfig(provider="default", model=model_id)
    settings.llm.pools["default"] = [LLMPoolEntry(model="default")]
    settings.llm.default_pool = "default"


def _ensure_workspace(settings: Settings) -> Path:
    """Return workspace path after ensuring it exists."""
    workspace = Path(settings.agents.workspace).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _copy_bootstrap_templates(workspace: Path, files: list[str]) -> tuple[list[str], list[str]]:
    """Create missing bootstrap files from bundled templates."""
    missing_files = [f for f in files if not (workspace / f).exists()]
    existing_files = [f for f in files if (workspace / f).exists()]

    for filename in missing_files:
        template_path = _BUNDLED_WORKSPACE / filename
        if template_path.exists():
            (workspace / filename).write_text(
                template_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            print(f"Created {workspace / filename}")

    return missing_files, existing_files


def _handle_existing_files_overwrite(workspace: Path, files: list[str]) -> None:
    """Prompt for overwrite decisions and apply selected template updates."""
    if not files:
        return

    listed = ", ".join(files)
    overwrite_all = input(f"\nExisting files: {listed}. Overwrite all? [y/N] ").strip().lower()
    if overwrite_all == "y":
        to_overwrite = files
    else:
        to_overwrite = [f for f in files if input(f"Overwrite {f}? [y/N] ").strip().lower() == "y"]

    for filename in to_overwrite:
        template_path = _BUNDLED_WORKSPACE / filename
        if template_path.exists():
            (workspace / filename).write_text(
                template_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            print(f"Updated {workspace / filename}")
        else:
            print(f"Warning: bundled template for {filename} not found, skipping")


def _ensure_bootstrap_md(workspace: Path, already_set_up: bool) -> None:
    """Create BOOTSTRAP.md on fresh setup, optionally on re-run."""
    bootstrap_path = workspace / "BOOTSTRAP.md"
    if bootstrap_path.exists():
        return
    if already_set_up:
        answer = (
            input("\nWorkspace already set up. Re-run bootstrap interview? [y/N] ").strip().lower()
        )
        if answer == "y":
            template_path = _BUNDLED_WORKSPACE / "BOOTSTRAP.md"
            bootstrap_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Created {bootstrap_path}")
            print("Start 'squidbot agent' to begin the bootstrap interview.")
        return

    template_path = _BUNDLED_WORKSPACE / "BOOTSTRAP.md"
    bootstrap_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Created {bootstrap_path}")


def _prompt_owner_aliases(settings: Settings, config_path: Path) -> None:
    """Prompt for owner aliases and save them when provided."""
    from squidbot.config.schema import OwnerAliasEntry  # noqa: PLC0415

    print("\nWhat names, nicknames, or addresses should I use to recognise you across channels?")
    print("Enter one alias per line. For channel-scoped aliases, use the format: address channel")
    print('(e.g. "@alex:matrix.org matrix" or "alex@example.com email")')
    print("Press Enter on an empty line when done.")

    aliases: list[OwnerAliasEntry] = []
    while True:
        line = input("> ").strip()
        if not line:
            break
        parts = line.split(None, 1)
        if len(parts) == 2:
            aliases.append(OwnerAliasEntry(address=parts[0], channel=parts[1]))
        else:
            aliases.append(OwnerAliasEntry(address=parts[0]))

    if aliases:
        settings.owner.aliases = aliases
        settings.save(config_path)
        print(f"Saved {len(aliases)} alias(es).")
