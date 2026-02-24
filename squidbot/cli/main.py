"""
CLI entry point for squidbot.

Commands:
  squidbot agent          Interactive chat (CLI channel)
  squidbot agent -m MSG   Single message mode
  squidbot gateway        Start gateway (all enabled channels)
  squidbot status         Show configuration and status
  squidbot onboard        Run interactive setup wizard
  squidbot cron list      List scheduled jobs
  squidbot cron add       Add a scheduled job
  squidbot cron remove    Remove a scheduled job
  squidbot skills list    List all discovered skills
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import cyclopts

from squidbot.cli.cron import cron_app
from squidbot.cli.gateway import (
    _make_agent_loop,
    _run_gateway,
    _setup_logging,
)
from squidbot.cli.onboard import (
    _copy_bootstrap_templates,
    _ensure_bootstrap_md,
    _ensure_workspace,
    _handle_existing_files_overwrite,
    _load_or_init_settings,
    _prompt_llm_settings,
    _prompt_owner_aliases,
)
from squidbot.cli.skills import skills_app
from squidbot.config.schema import DEFAULT_CONFIG_PATH, Settings

if TYPE_CHECKING:
    from squidbot.core.ports import ChannelPort

app = cyclopts.App(name="squidbot", help="A lightweight personal AI assistant.")

# Register subcommand apps
app.command(cron_app)
app.command(skills_app)


@app.command
def agent(
    message: str | None = None,
    config: Path = DEFAULT_CONFIG_PATH,
    log_level: str = "INFO",
) -> None:
    """
    Chat with the assistant.

    In interactive mode (no --message), starts a REPL loop.
    With --message, sends a single message and exits.
    """
    _setup_logging(log_level)
    asyncio.run(_run_agent(message=message, config_path=config))


@app.command
def gateway(config: Path = DEFAULT_CONFIG_PATH, log_level: str = "INFO") -> None:
    """Start the gateway (all enabled channels run concurrently)."""
    _setup_logging(log_level)
    asyncio.run(_run_gateway(config_path=config))


@app.command
def status(config: Path = DEFAULT_CONFIG_PATH) -> None:
    """Show the current configuration and channel status."""
    settings = Settings.load(config)
    pool_count = len(settings.llm.pools)
    print(f"Pools:     {pool_count} configured (default: {settings.llm.default_pool})")
    print(f"Matrix:    {'enabled' if settings.channels.matrix.enabled else 'disabled'}")
    print(f"Email:     {'enabled' if settings.channels.email.enabled else 'disabled'}")
    print(f"Workspace: {settings.agents.workspace}")


@app.command
def onboard(config: Path = DEFAULT_CONFIG_PATH) -> None:
    """Run the interactive setup wizard."""
    asyncio.run(_run_onboard(config_path=config))


# Files copied by the onboard wizard — excludes BOOTSTRAP.md (managed separately)
BOOTSTRAP_FILES_ONBOARD: list[str] = [
    "SOUL.md",
    "IDENTITY.md",
    "USER.md",
    "AGENTS.md",
    "ENVIRONMENT.md",
]


async def _run_agent(message: str | None, config_path: Path) -> None:
    """Run the CLI channel agent."""
    from rich.console import Console  # noqa: PLC0415
    from rich.rule import Rule  # noqa: PLC0415

    from squidbot.adapters.channels.cli import CliChannel, RichCliChannel  # noqa: PLC0415

    settings = Settings.load(config_path)
    agent_loop, mcp_connections, storage = await _make_agent_loop(settings)

    channel: ChannelPort
    if message:
        # Single-shot mode: use plain CliChannel (streaming, no banner)
        channel = CliChannel()
        from squidbot.adapters.tools.memory_write import MemoryWriteTool  # noqa: PLC0415

        extra = [MemoryWriteTool(storage=storage)]
        await agent_loop.run(CliChannel.SESSION, message, channel, extra_tools=extra)
        print()  # newline after streamed output
        for conn in mcp_connections:
            await conn.close()
        return

    # Interactive REPL mode: Rich interface
    console = Console()
    console.print(
        f"🦑 [bold]squidbot[/bold] 0.1.0  •  pool: [cyan]{settings.llm.default_pool}[/cyan]"
    )
    console.print(Rule(style="dim"))
    console.print("[dim]type 'exit' or Ctrl+D to quit[/dim]")

    channel = RichCliChannel()
    workspace = Path(settings.agents.workspace).expanduser()
    try:
        # If BOOTSTRAP.md exists, trigger the bootstrap interview before the user speaks
        if (workspace / "BOOTSTRAP.md").exists():
            console.print("[dim]first run — starting bootstrap interview…[/dim]")
            console.print(Rule(style="dim"))
            session = CliChannel.SESSION
            from squidbot.adapters.tools.memory_write import MemoryWriteTool  # noqa: PLC0415

            extra = [MemoryWriteTool(storage=storage)]
            await agent_loop.run(
                session,
                "BOOTSTRAP.md exists. Follow it now.",
                channel,
                extra_tools=extra,
            )
        async for inbound in channel.receive():
            from squidbot.adapters.tools.memory_write import MemoryWriteTool  # noqa: PLC0415

            extra = [MemoryWriteTool(storage=storage)]
            await agent_loop.run(inbound.session, inbound.text, channel, extra_tools=extra)
    finally:
        for conn in mcp_connections:
            await conn.close()


async def _run_onboard(config_path: Path) -> None:
    """Interactive setup wizard. Idempotent — existing values shown as defaults."""
    settings = _load_or_init_settings(config_path)
    _prompt_llm_settings(settings)

    settings.save(config_path)
    print(f"\nConfiguration saved to {config_path}")

    workspace = _ensure_workspace(settings)

    # Determine bootstrap state BEFORE copying any files
    bootstrap_path = workspace / "BOOTSTRAP.md"
    already_set_up = (workspace / "IDENTITY.md").exists() and not bootstrap_path.exists()

    _, existing_files = _copy_bootstrap_templates(workspace, BOOTSTRAP_FILES_ONBOARD)
    _handle_existing_files_overwrite(workspace, existing_files)
    _ensure_bootstrap_md(workspace, already_set_up)

    _prompt_owner_aliases(settings, config_path)

    print("Run 'squidbot agent' to start chatting!")


def main() -> None:
    """Run the squidbot CLI application."""
    app()


if __name__ == "__main__":
    main()
