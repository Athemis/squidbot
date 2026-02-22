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

import cyclopts

from squidbot.config.schema import DEFAULT_CONFIG_PATH, Settings

app = cyclopts.App(name="squidbot", help="A lightweight personal AI assistant.")


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
    print(f"Model:     {settings.llm.model}")
    print(f"API:       {settings.llm.api_base}")
    print(f"Matrix:    {'enabled' if settings.channels.matrix.enabled else 'disabled'}")
    print(f"Email:     {'enabled' if settings.channels.email.enabled else 'disabled'}")
    print(f"Workspace: {settings.agents.workspace}")


@app.command
def onboard(config: Path = DEFAULT_CONFIG_PATH) -> None:
    """Run the interactive setup wizard."""
    asyncio.run(_run_onboard(config_path=config))


# ── Cron subcommands ────────────────────────────────────────────────────────

cron_app = cyclopts.App(name="cron", help="Manage scheduled jobs.")
app.command(cron_app)


@cron_app.command
def list_jobs(config: Path = DEFAULT_CONFIG_PATH) -> None:
    """List all scheduled cron jobs."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory

    async def _list() -> None:
        storage = JsonlMemory(base_dir=Path.home() / ".squidbot")
        jobs = await storage.load_cron_jobs()
        if not jobs:
            print("No cron jobs configured.")
            return
        for job in jobs:
            state = "on" if job.enabled else "off"
            print(f"  [{state}] {job.id}  {job.name}")
            print(f"       schedule: {job.schedule}  channel: {job.channel}")
            print(f"       message:  {job.message}")

    asyncio.run(_list())


@cron_app.command
def add(
    name: str,
    message: str,
    schedule: str,
    channel: str = "cli:local",
    config: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Add a new cron job."""
    import uuid

    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.core.models import CronJob

    async def _add() -> None:
        storage = JsonlMemory(base_dir=Path.home() / ".squidbot")
        jobs = await storage.load_cron_jobs()
        job = CronJob(
            id=str(uuid.uuid4())[:8],
            name=name,
            message=message,
            schedule=schedule,
            channel=channel,
        )
        jobs.append(job)
        await storage.save_cron_jobs(jobs)
        print(f"Added cron job '{name}' (id={job.id})")

    asyncio.run(_add())


@cron_app.command
def remove(job_id: str, config: Path = DEFAULT_CONFIG_PATH) -> None:
    """Remove a cron job by ID."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory

    async def _remove() -> None:
        storage = JsonlMemory(base_dir=Path.home() / ".squidbot")
        jobs = await storage.load_cron_jobs()
        before = len(jobs)
        jobs = [j for j in jobs if j.id != job_id]
        if len(jobs) == before:
            print(f"No job found with id '{job_id}'")
            return
        await storage.save_cron_jobs(jobs)
        print(f"Removed job '{job_id}'")

    asyncio.run(_remove())


# ── Skills subcommands ───────────────────────────────────────────────────────

skills_app = cyclopts.App(name="skills", help="Manage squidbot skills.")
app.command(skills_app)


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


# ── Internal helpers ─────────────────────────────────────────────────────────


_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _setup_logging(level: str) -> None:
    """
    Configure loguru for gateway/agent output.

    Removes the default loguru stderr handler and replaces it with one that
    uses a consistent timestamp+level format. Third-party libraries that are
    too chatty at DEBUG are clamped to WARNING via the stdlib logging bridge.

    Args:
        level: Log level string (case-insensitive), e.g. "INFO", "DEBUG".

    Raises:
        SystemExit: If the level is not a valid log level name.
    """
    import logging
    import sys

    from loguru import logger

    normalised = level.upper()
    if normalised not in _VALID_LOG_LEVELS:
        valid = ", ".join(sorted(_VALID_LOG_LEVELS))
        print(f"error: invalid --log-level '{level}'. Valid values: {valid}", file=sys.stderr)
        raise SystemExit(1)

    logger.remove()  # remove loguru's built-in default handler
    logger.add(
        sys.stderr,
        level=normalised,
        format=("<green>{time:YYYY-MM-DD HH:mm:ss}</green> <level>{level:<8}</level> {message}"),
        colorize=True,
    )
    for noisy in ("httpx", "nio", "aioimaplib", "aiosmtplib", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def _make_agent_loop(settings: Settings):
    """Construct the agent loop from configuration."""
    from squidbot.adapters.llm.openai import OpenAIAdapter
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.adapters.skills.fs import FsSkillsLoader
    from squidbot.adapters.tools.files import ListFilesTool, ReadFileTool, WriteFileTool
    from squidbot.adapters.tools.shell import ShellTool
    from squidbot.core.agent import AgentLoop
    from squidbot.core.memory import MemoryManager
    from squidbot.core.registry import ToolRegistry

    # Resolve workspace path
    workspace = Path(settings.agents.workspace).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)

    # Build storage directory
    storage_dir = Path.home() / ".squidbot"
    storage = JsonlMemory(base_dir=storage_dir)

    # Skills loader (extra dirs → workspace/skills → bundled)
    bundled_skills = Path(__file__).parent.parent / "skills"
    extra_dirs = [Path(d).expanduser() for d in settings.skills.extra_dirs]
    skills = FsSkillsLoader(search_dirs=extra_dirs + [workspace / "skills", bundled_skills])

    memory = MemoryManager(storage=storage, max_history_messages=200, skills=skills)

    # LLM adapter
    llm = OpenAIAdapter(
        api_base=settings.llm.api_base,
        api_key=settings.llm.api_key,
        model=settings.llm.model,
    )

    # Tool registry
    registry = ToolRegistry()
    restrict = settings.agents.restrict_to_workspace

    if settings.tools.shell.enabled:
        registry.register(ShellTool(workspace=workspace, restrict_to_workspace=restrict))
    registry.register(ReadFileTool(workspace=workspace, restrict_to_workspace=restrict))
    registry.register(WriteFileTool(workspace=workspace, restrict_to_workspace=restrict))
    registry.register(ListFilesTool(workspace=workspace, restrict_to_workspace=restrict))

    if settings.tools.web_search.enabled:
        from squidbot.adapters.tools.web_search import WebSearchTool  # noqa: PLC0415

        registry.register(WebSearchTool(config=settings.tools.web_search))

    # Load system prompt
    system_prompt_path = workspace / settings.agents.system_prompt_file
    if system_prompt_path.exists():
        system_prompt = system_prompt_path.read_text(encoding="utf-8")
    else:
        system_prompt = "You are a helpful personal AI assistant."

    return AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt=system_prompt)


async def _run_agent(message: str | None, config_path: Path) -> None:
    """Run the CLI channel agent."""
    from rich.console import Console
    from rich.rule import Rule

    from squidbot.adapters.channels.cli import CliChannel, RichCliChannel

    settings = Settings.load(config_path)
    agent_loop = await _make_agent_loop(settings)

    if message:
        # Single-shot mode: use plain CliChannel (streaming, no banner)
        channel = CliChannel()
        await agent_loop.run(CliChannel.SESSION, message, channel)
        print()  # newline after streamed output
        return

    # Interactive REPL mode: Rich interface
    console = Console()
    console.print(f"🦑 [bold]squidbot[/bold] 0.1.0  •  model: [cyan]{settings.llm.model}[/cyan]")
    console.print(Rule(style="dim"))
    console.print("[dim]type 'exit' or Ctrl+D to quit[/dim]")

    channel = RichCliChannel()
    async for inbound in channel.receive():
        await agent_loop.run(inbound.session, inbound.text, channel)


async def _run_gateway(config_path: Path) -> None:
    """Start all enabled channels concurrently.

    The gateway does not start a CLI channel — use `squidbot agent` for
    interactive terminal use. Log output goes to stdout; control the bot
    via Matrix or Email.
    """
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.core.heartbeat import HeartbeatService, LastChannelTracker
    from squidbot.core.models import Session
    from squidbot.core.scheduler import CronScheduler

    settings = Settings.load(config_path)
    agent_loop = await _make_agent_loop(settings)
    storage = JsonlMemory(base_dir=Path.home() / ".squidbot")
    workspace = Path(settings.agents.workspace).expanduser()

    tracker = LastChannelTracker()

    # Map of channel prefix → channel instance for cron job routing
    channel_registry: dict[str, object] = {}

    async def on_cron_due(job) -> None:
        """Deliver a scheduled message to the job's target channel."""
        channel_prefix = job.channel.split(":")[0]
        ch = channel_registry.get(channel_prefix)
        if ch is None:
            return  # target channel not active
        session = Session(
            channel=channel_prefix,
            sender_id=job.channel.split(":", 1)[1],
        )
        await agent_loop.run(session, job.message, ch)  # type: ignore[arg-type]

    scheduler = CronScheduler(storage=storage)
    heartbeat = HeartbeatService(
        agent_loop=agent_loop,
        tracker=tracker,
        workspace=workspace,
        config=settings.agents.heartbeat,
    )

    async with asyncio.TaskGroup() as tg:
        tg.create_task(scheduler.run(on_due=on_cron_due))
        tg.create_task(heartbeat.run())


async def _run_onboard(config_path: Path) -> None:
    """Interactive setup wizard."""
    print("squidbot setup wizard")
    print("=" * 40)
    api_base = input("LLM API base URL [https://openrouter.ai/api/v1]: ").strip()
    api_key = input("API key: ").strip()
    model = input("Model [anthropic/claude-opus-4-5]: ").strip()

    settings = Settings()
    if api_base:
        settings.llm.api_base = api_base
    if api_key:
        settings.llm.api_key = api_key
    if model:
        settings.llm.model = model

    settings.save(config_path)
    print(f"\nConfiguration saved to {config_path}")
    print("Run 'squidbot agent' to start chatting!")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
