"""Tests for the squidbot onboard wizard (_run_onboard)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from squidbot.cli.main import BOOTSTRAP_FILES_MAIN, _run_onboard
from squidbot.config.schema import Settings


def _make_settings(workspace: Path) -> Settings:
    """Return a fresh Settings instance pointing workspace at tmp_path."""
    s = Settings()
    s.agents.workspace = str(workspace)
    return s


# ── Config: fresh start ───────────────────────────────────────────────────────


async def test_onboard_fresh_uses_defaults_on_empty_input(tmp_path: Path) -> None:
    """Empty input on fresh start → built-in defaults are saved."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"

    settings = _make_settings(workspace)
    with (
        patch("squidbot.cli.main.input", side_effect=["", "", ""]),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    saved = Settings.load(config_path)
    provider = saved.llm.providers["default"]
    model = saved.llm.models["default"]
    assert provider.api_base == "https://openrouter.ai/api/v1"
    assert provider.api_key == ""
    assert model.model == "anthropic/claude-opus-4-5"


async def test_onboard_fresh_saves_provided_values(tmp_path: Path) -> None:
    """Provided input on fresh start → those values are saved."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"

    settings = _make_settings(workspace)
    with (
        patch(
            "squidbot.cli.main.input",
            side_effect=["https://api.example.com/v1", "sk-test", "gpt-4o"],
        ),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    saved = Settings.load(config_path)
    provider = saved.llm.providers["default"]
    model = saved.llm.models["default"]
    assert provider.api_base == "https://api.example.com/v1"
    assert provider.api_key == "sk-test"
    assert model.model == "gpt-4o"


# ── Config: idempotency ───────────────────────────────────────────────────────


async def test_onboard_existing_config_kept_on_empty_input(tmp_path: Path) -> None:
    """Empty input when config exists → existing values preserved."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"

    # First run: save initial values
    settings = _make_settings(workspace)
    with (
        patch(
            "squidbot.cli.main.input",
            side_effect=["https://first.example.com/v1", "sk-first", "claude-3"],
        ),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    # Second run: empty input — existing values must be kept
    real_load = Settings.load

    def load_with_workspace(path: Path) -> Settings:
        s = real_load(path)
        s.agents.workspace = str(workspace)
        return s

    with (
        # api_base, api_key, model, overwrite-all=N, N×5 per-file (one per BOOTSTRAP_FILES_MAIN)
        patch("squidbot.cli.main.input", side_effect=["", "", "", "N", "N", "N", "N", "N", "N"]),
        patch("squidbot.cli.main.Settings.load", side_effect=load_with_workspace),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    saved = Settings.load(config_path)
    provider = saved.llm.providers["default"]
    model = saved.llm.models["default"]
    assert provider.api_base == "https://first.example.com/v1"
    assert provider.api_key == "sk-first"
    assert model.model == "claude-3"


async def test_onboard_existing_config_overwritten_with_new_input(tmp_path: Path) -> None:
    """New input when config exists → new values saved."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"

    settings = _make_settings(workspace)
    with (
        patch(
            "squidbot.cli.main.input",
            side_effect=["https://first.example.com/v1", "sk-first", "claude-3"],
        ),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    real_load = Settings.load

    def load_with_workspace(path: Path) -> Settings:
        s = real_load(path)
        s.agents.workspace = str(workspace)
        return s

    with (
        patch(
            "squidbot.cli.main.input",
            side_effect=[
                # api_base, api_key, model
                "https://second.example.com/v1",
                "sk-second",
                "gpt-4o",
                # overwrite-all=N, then N×5 per-file (one per BOOTSTRAP_FILES_MAIN)
                "N",
                "N",
                "N",
                "N",
                "N",
                "N",
            ],
        ),
        patch("squidbot.cli.main.Settings.load", side_effect=load_with_workspace),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    saved = Settings.load(config_path)
    provider = saved.llm.providers["default"]
    model = saved.llm.models["default"]
    assert provider.api_base == "https://second.example.com/v1"
    assert provider.api_key == "sk-second"
    assert model.model == "gpt-4o"


# ── Workspace files ───────────────────────────────────────────────────────────


async def test_onboard_creates_bootstrap_files_on_fresh_workspace(tmp_path: Path) -> None:
    """Fresh workspace → all BOOTSTRAP_FILES_MAIN + BOOTSTRAP.md are created."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"

    settings = _make_settings(workspace)
    with (
        patch("squidbot.cli.main.input", side_effect=["", "", ""]),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    for filename in BOOTSTRAP_FILES_MAIN:
        assert (workspace / filename).exists(), f"{filename} not created"
    assert (workspace / "BOOTSTRAP.md").exists()


async def test_onboard_does_not_overwrite_existing_files(tmp_path: Path) -> None:
    """Existing workspace files are not overwritten on re-run."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("my custom agents", encoding="utf-8")
    (workspace / "IDENTITY.md").write_text("my identity", encoding="utf-8")

    def load_with_workspace(path: Path) -> Settings:
        s = Settings.load(path)
        s.agents.workspace = str(workspace)
        return s

    settings = _make_settings(workspace)
    with (
        # api_base, api_key, model
        # overwrite-all=N, per-file AGENTS.md=N, per-file IDENTITY.md=N, bootstrap-rerun=N
        patch("squidbot.cli.main.input", side_effect=["", "", "", "N", "N", "N", "N"]),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("squidbot.cli.main.Settings.load", side_effect=load_with_workspace),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    assert (workspace / "AGENTS.md").read_text(encoding="utf-8") == "my custom agents"
    assert (workspace / "IDENTITY.md").read_text(encoding="utf-8") == "my identity"


# ── Bootstrap re-run prompt ───────────────────────────────────────────────────


async def test_onboard_no_bootstrap_rerun_prompt_on_fresh_workspace(tmp_path: Path) -> None:
    """Fresh workspace (no IDENTITY.md) → no re-run prompt, BOOTSTRAP.md created."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"

    prompts: list[str] = []

    def capturing_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return ""

    settings = _make_settings(workspace)
    with (
        patch("squidbot.cli.main.input", side_effect=capturing_input),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    assert not any("bootstrap" in p.lower() for p in prompts)
    assert (workspace / "BOOTSTRAP.md").exists()


async def test_onboard_offers_bootstrap_rerun_when_already_set_up(tmp_path: Path) -> None:
    """IDENTITY.md exists, BOOTSTRAP.md gone → re-run prompt appears."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "IDENTITY.md").write_text("identity", encoding="utf-8")

    prompts: list[str] = []
    inputs = ["", "", "", "N", "N", "N"]

    def capturing_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return inputs.pop(0) if inputs else ""

    def load_with_workspace(path: Path) -> Settings:
        s = Settings.load(path)
        s.agents.workspace = str(workspace)
        return s

    settings = _make_settings(workspace)
    with (
        patch("squidbot.cli.main.input", side_effect=capturing_input),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("squidbot.cli.main.Settings.load", side_effect=load_with_workspace),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    assert any("bootstrap" in p.lower() for p in prompts)
    assert not (workspace / "BOOTSTRAP.md").exists()


async def test_onboard_bootstrap_rerun_yes_creates_file(tmp_path: Path) -> None:
    """Answering 'y' to re-run prompt creates BOOTSTRAP.md."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "IDENTITY.md").write_text("identity", encoding="utf-8")

    def load_with_workspace(path: Path) -> Settings:
        s = Settings.load(path)
        s.agents.workspace = str(workspace)
        return s

    settings = _make_settings(workspace)
    with (
        patch("squidbot.cli.main.input", side_effect=["", "", "", "N", "N", "y"]),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("squidbot.cli.main.Settings.load", side_effect=load_with_workspace),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    assert (workspace / "BOOTSTRAP.md").exists()


async def test_onboard_bootstrap_rerun_no_does_not_create_file(tmp_path: Path) -> None:
    """Answering 'N' to re-run prompt does not create BOOTSTRAP.md."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "IDENTITY.md").write_text("identity", encoding="utf-8")

    def load_with_workspace(path: Path) -> Settings:
        s = Settings.load(path)
        s.agents.workspace = str(workspace)
        return s

    settings = _make_settings(workspace)
    with (
        patch("squidbot.cli.main.input", side_effect=["", "", "", "N", "N", "N"]),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("squidbot.cli.main.Settings.load", side_effect=load_with_workspace),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    assert not (workspace / "BOOTSTRAP.md").exists()


# ── Overwrite prompt ──────────────────────────────────────────────────────────


async def test_onboard_overwrite_all_yes_replaces_existing_files(tmp_path: Path) -> None:
    """'y' to overwrite-all → existing files are replaced with bundled templates."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("old soul", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("old agents", encoding="utf-8")

    settings = _make_settings(workspace)
    with (
        patch("squidbot.cli.main.input", side_effect=["", "", "", "y"]),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    assert (workspace / "SOUL.md").read_text(encoding="utf-8") != "old soul"
    assert (workspace / "AGENTS.md").read_text(encoding="utf-8") != "old agents"


async def test_onboard_overwrite_all_no_then_per_file_yes_replaces(tmp_path: Path) -> None:
    """'n' to overwrite-all, then 'y' per file → that file is replaced."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("old soul", encoding="utf-8")

    settings = _make_settings(workspace)
    # inputs: api_base, api_key, model, overwrite_all=n, overwrite_SOUL.md=y
    with (
        patch("squidbot.cli.main.input", side_effect=["", "", "", "n", "y"]),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    assert (workspace / "SOUL.md").read_text(encoding="utf-8") != "old soul"


async def test_onboard_overwrite_all_no_then_per_file_no_keeps(tmp_path: Path) -> None:
    """'n' to overwrite-all, then 'n' per file → file is kept."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("old soul", encoding="utf-8")

    settings = _make_settings(workspace)
    # inputs: api_base, api_key, model, overwrite_all=n, overwrite_SOUL.md=n
    with (
        patch("squidbot.cli.main.input", side_effect=["", "", "", "n", "n"]),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    assert (workspace / "SOUL.md").read_text(encoding="utf-8") == "old soul"


async def test_onboard_no_overwrite_prompt_when_no_existing_files(tmp_path: Path) -> None:
    """Fresh workspace (no existing files) → no overwrite prompt shown."""
    config_path = tmp_path / "squidbot.yaml"
    workspace = tmp_path / "workspace"

    prompts: list[str] = []

    def capturing_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return ""

    settings = _make_settings(workspace)
    with (
        patch("squidbot.cli.main.input", side_effect=capturing_input),
        patch("squidbot.cli.main.Settings", return_value=settings),
        patch("builtins.print"),
    ):
        await _run_onboard(config_path)

    assert not any("overwrite" in p.lower() for p in prompts)
