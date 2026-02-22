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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cyclopts

from squidbot.config.schema import DEFAULT_CONFIG_PATH, Settings

if TYPE_CHECKING:
    from squidbot.adapters.tools.mcp import McpConnectionProtocol
    from squidbot.core.agent import AgentLoop
    from squidbot.core.models import ChannelStatus, CronJob, SessionInfo
    from squidbot.core.ports import ChannelPort
    from squidbot.core.skills import SkillMetadata


@dataclass
class GatewayState:
    """
    Live runtime state of the gateway process.

    Updated by _channel_loop_with_state() and channel setup code.
    Consumed by GatewayStatusAdapter for dashboards and status reporting.
    """

    active_sessions: dict[str, SessionInfo]
    channel_status: list[ChannelStatus]
    cron_jobs_cache: list[CronJob]
    started_at: datetime = field(default_factory=datetime.now)


class GatewayStatusAdapter:
    """
    Implements StatusPort by reading from GatewayState.

    Args:
        state: The live gateway state object.
        skills_loader: SkillsPort implementation for get_skills().
    """

    def __init__(self, state: GatewayState, skills_loader: Any) -> None:
        """Initialize with the given state and skills loader."""
        self._state = state
        self._skills_loader = skills_loader

    def get_active_sessions(self) -> list[SessionInfo]:
        """Return all sessions seen since gateway start."""
        return list(self._state.active_sessions.values())

    def get_channel_status(self) -> list[ChannelStatus]:
        """Return the status of all configured channels."""
        return list(self._state.channel_status)

    def get_cron_jobs(self) -> list[CronJob]:
        """Return the current cron job list from the in-memory cache."""
        return list(self._state.cron_jobs_cache)

    def get_skills(self) -> list[SkillMetadata]:
        """Return all discovered skills via the skills loader."""
        return self._skills_loader.list_skills()  # type: ignore[no-any-return]


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
    pool_count = len(settings.llm.pools)
    print(f"Pools:     {pool_count} configured (default: {settings.llm.default_pool})")
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


def _print_banner(settings: Settings) -> None:
    """
    Print the gateway startup banner to stderr.

    Uses plain print() rather than loguru so the banner is not prefixed
    with a timestamp and log level.

    Args:
        settings: Loaded application settings.
    """
    import sys
    from importlib.metadata import version

    ver = version("squidbot")
    pool = settings.llm.default_pool
    workspace = Path(settings.agents.workspace).expanduser().resolve()
    print(f"🦑 squidbot v{ver}", file=sys.stderr)
    print(f"   pool:      {pool}", file=sys.stderr)
    print(f"   workspace: {workspace}", file=sys.stderr)
    print(f"   {'─' * 40}", file=sys.stderr)
    print(file=sys.stderr)


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


def _resolve_llm(settings: Settings) -> Any:
    """
    Construct an OpenAIAdapter from the new provider/model/pool schema.

    Resolves the default pool to its first model entry, then looks up the
    model and provider configuration to obtain API credentials and model ID.
    Falls back to an unconfigured adapter when no pool/model/provider is defined
    (e.g., in tests that mock AsyncOpenAI directly).

    Args:
        settings: Loaded application settings.

    Returns:
        An OpenAIAdapter instance.
    """
    from squidbot.adapters.llm.openai import OpenAIAdapter  # noqa: PLC0415

    pool_name = settings.llm.default_pool
    pool_entries = settings.llm.pools.get(pool_name, [])

    if pool_entries:
        model_name = pool_entries[0].model
        model_cfg = settings.llm.models.get(model_name)
        if model_cfg is not None:
            provider_cfg = settings.llm.providers.get(model_cfg.provider)
            if provider_cfg is not None:
                return OpenAIAdapter(
                    api_base=provider_cfg.api_base,
                    api_key=provider_cfg.api_key,
                    model=model_cfg.model,
                )

    # No pool/model/provider configured — construct with empty credentials.
    # In production this will fail when the first LLM call is made; tests that
    # mock AsyncOpenAI will proceed normally.
    return OpenAIAdapter(api_base="", api_key="", model="")


async def _make_agent_loop(
    settings: Settings,
    storage_dir: Path | None = None,
) -> tuple[AgentLoop, list[McpConnectionProtocol]]:
    """
    Construct the agent loop from configuration.

    Args:
        settings: Loaded application settings.
        storage_dir: Override the storage directory. Defaults to ~/.squidbot.

    Returns:
        Tuple of (agent_loop, mcp_connections). Callers must close mcp_connections
        on shutdown by calling conn.close() on each.
    """
    from squidbot.adapters.persistence.jsonl import JsonlMemory  # noqa: PLC0415
    from squidbot.adapters.skills.fs import FsSkillsLoader  # noqa: PLC0415
    from squidbot.adapters.tools.files import (  # noqa: PLC0415
        ListFilesTool,
        ReadFileTool,
        WriteFileTool,
    )
    from squidbot.adapters.tools.shell import ShellTool  # noqa: PLC0415
    from squidbot.core.agent import AgentLoop  # noqa: PLC0415
    from squidbot.core.memory import MemoryManager  # noqa: PLC0415
    from squidbot.core.registry import ToolRegistry  # noqa: PLC0415

    # Resolve workspace path
    workspace = Path(settings.agents.workspace).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)

    # Build storage directory
    _storage_dir = storage_dir or Path.home() / ".squidbot"
    storage = JsonlMemory(base_dir=_storage_dir)

    # Skills loader (extra dirs → workspace/skills → bundled)
    bundled_skills = Path(__file__).parent.parent / "skills"
    extra_dirs = [Path(d).expanduser() for d in settings.skills.extra_dirs]
    skills = FsSkillsLoader(search_dirs=extra_dirs + [workspace / "skills", bundled_skills])

    memory = MemoryManager(storage=storage, max_history_messages=200, skills=skills)

    # LLM adapter — resolved from pool/model/provider schema
    llm = _resolve_llm(settings)

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

    # MCP servers
    mcp_connections: list[McpConnectionProtocol] = []
    if settings.tools.mcp_servers:
        from squidbot.adapters.tools.mcp import McpServerConnection  # noqa: PLC0415

        for server_name, server_cfg in settings.tools.mcp_servers.items():
            conn = McpServerConnection(name=server_name, config=server_cfg)
            tools = await conn.connect()
            for tool in tools:
                registry.register(tool)
            mcp_connections.append(conn)

    # Load system prompt
    system_prompt_path = workspace / settings.agents.system_prompt_file
    if system_prompt_path.exists():
        system_prompt = system_prompt_path.read_text(encoding="utf-8")
    else:
        system_prompt = "You are a helpful personal AI assistant."

    # Spawn tool profile injection into system prompt
    if settings.tools.spawn.enabled and settings.tools.spawn.profiles:
        import html  # noqa: PLC0415

        profile_lines = []
        for pname, prof in settings.tools.spawn.profiles.items():
            tools_str = ", ".join(prof.tools) if prof.tools else "all"
            profile_lines.append(
                f'  <profile name="{html.escape(pname)}">'
                f"{html.escape(prof.system_prompt)} Tools: {html.escape(tools_str)}."
                f"</profile>"
            )
        profiles_xml = (
            "<available_spawn_profiles>\n"
            + "\n".join(profile_lines)
            + "\n</available_spawn_profiles>"
        )
        system_prompt = system_prompt + "\n\n" + profiles_xml

    agent_loop = AgentLoop(llm=llm, memory=memory, registry=registry, system_prompt=system_prompt)

    if settings.tools.spawn.enabled:
        # SubAgentFactory holds a live reference to `registry`. SpawnTool and
        # SpawnAwaitTool are registered into it below, and SubAgentFactory.build()
        # explicitly filters them out via _SPAWN_TOOL_NAMES — so the ordering is
        # intentional: the factory sees the spawn tools and skips them.
        from squidbot.adapters.tools.spawn import (  # noqa: PLC0415
            JobStore,
            SpawnAwaitTool,
            SpawnTool,
            SubAgentFactory,
        )

        spawn_factory = SubAgentFactory(
            llm=llm,
            memory=memory,
            registry=registry,
            system_prompt=system_prompt,
            profiles=settings.tools.spawn.profiles,
        )
        job_store = JobStore()
        registry.register(SpawnTool(factory=spawn_factory, job_store=job_store))
        registry.register(SpawnAwaitTool(job_store=job_store))

    return agent_loop, mcp_connections


async def _run_agent(message: str | None, config_path: Path) -> None:
    """Run the CLI channel agent."""
    from rich.console import Console  # noqa: PLC0415
    from rich.rule import Rule  # noqa: PLC0415

    from squidbot.adapters.channels.cli import CliChannel, RichCliChannel  # noqa: PLC0415

    settings = Settings.load(config_path)
    agent_loop, mcp_connections = await _make_agent_loop(settings)

    channel: ChannelPort
    if message:
        # Single-shot mode: use plain CliChannel (streaming, no banner)
        channel = CliChannel()
        await agent_loop.run(CliChannel.SESSION, message, channel)
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
    try:
        async for inbound in channel.receive():
            await agent_loop.run(inbound.session, inbound.text, channel)
    finally:
        for conn in mcp_connections:
            await conn.close()


async def _channel_loop_with_state(
    channel: ChannelPort,
    loop: Any,
    state: GatewayState,
) -> None:
    """
    Drive a single channel and update GatewayState on each message.

    Creates a SessionInfo entry on first message from a session, then increments
    message_count on subsequent messages.

    Args:
        channel: The channel adapter to drive.
        loop: The agent loop to handle each message.
        state: Live gateway state — updated in-place.
    """
    from squidbot.core.models import SessionInfo  # noqa: PLC0415

    async for inbound in channel.receive():
        sid = inbound.session.id
        if sid in state.active_sessions:
            state.active_sessions[sid].message_count += 1
        else:
            state.active_sessions[sid] = SessionInfo(
                session_id=sid,
                channel=inbound.session.channel,
                sender_id=inbound.session.sender_id,
                started_at=datetime.now(),
                message_count=1,
            )
        await loop.run(inbound.session, inbound.text, channel)


async def _channel_loop(channel: ChannelPort, loop: Any) -> None:
    """
    Drive a single channel without state tracking (used by agent command).

    Args:
        channel: The channel adapter to drive.
        loop: The agent loop to handle each message.
    """
    async for inbound in channel.receive():
        await loop.run(inbound.session, inbound.text, channel)


async def _run_gateway(config_path: Path) -> None:
    """Start all enabled channels concurrently.

    The gateway does not start a CLI channel — use `squidbot agent` for
    interactive terminal use. Log output goes to stderr; control the bot
    via Matrix or Email.
    """
    from loguru import logger  # noqa: PLC0415

    from squidbot.adapters.persistence.jsonl import JsonlMemory  # noqa: PLC0415
    from squidbot.core.heartbeat import HeartbeatService, LastChannelTracker  # noqa: PLC0415
    from squidbot.core.models import Session  # noqa: PLC0415
    from squidbot.core.scheduler import CronScheduler  # noqa: PLC0415

    settings = Settings.load(config_path)
    _print_banner(settings)

    # Startup summary
    logger.info("gateway starting")
    matrix_state = "enabled" if settings.channels.matrix.enabled else "disabled"
    email_state = "enabled" if settings.channels.email.enabled else "disabled"
    logger.info("matrix: {}", matrix_state)
    logger.info("email: {}", email_state)

    hb = settings.agents.heartbeat
    if hb.enabled:
        logger.info(
            "heartbeat: every {}m, active {}-{} {}",
            hb.interval_minutes,
            hb.active_hours_start,
            hb.active_hours_end,
            hb.timezone,
        )
    else:
        logger.info("heartbeat: disabled")

    from squidbot.core.models import ChannelStatus  # noqa: PLC0415

    storage = JsonlMemory(base_dir=Path.home() / ".squidbot")
    cron_jobs = await storage.load_cron_jobs()
    logger.info("cron: {} jobs loaded", len(cron_jobs))

    agent_loop, mcp_connections = await _make_agent_loop(settings)
    workspace = Path(settings.agents.workspace).expanduser()

    tracker = LastChannelTracker()

    # Live gateway state — updated by _channel_loop_with_state and channel setup
    state = GatewayState(
        active_sessions={},
        channel_status=[],
        cron_jobs_cache=list(cron_jobs),
        started_at=datetime.now(),
    )

    # Map of channel prefix → channel instance for cron job routing
    channel_registry: dict[str, object] = {}

    async def on_cron_due(job: CronJob) -> None:
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

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(scheduler.run(on_due=on_cron_due))
            tg.create_task(heartbeat.run())
            if settings.channels.matrix.enabled:
                from squidbot.adapters.channels.matrix import MatrixChannel  # noqa: PLC0415

                matrix_ch = MatrixChannel(config=settings.channels.matrix)
                channel_registry["matrix"] = matrix_ch
                state.channel_status.append(
                    ChannelStatus(name="matrix", enabled=True, connected=True)
                )
                logger.info("matrix channel: starting")
                tg.create_task(_channel_loop_with_state(matrix_ch, agent_loop, state))
            else:
                state.channel_status.append(
                    ChannelStatus(name="matrix", enabled=False, connected=False)
                )
                logger.info("matrix channel: disabled")
            if settings.channels.email.enabled:
                from squidbot.adapters.channels.email import EmailChannel  # noqa: PLC0415

                email_ch = EmailChannel(config=settings.channels.email)
                channel_registry["email"] = email_ch
                state.channel_status.append(
                    ChannelStatus(name="email", enabled=True, connected=True)
                )
                logger.info("email channel: starting")
                tg.create_task(_channel_loop_with_state(email_ch, agent_loop, state))
            else:
                state.channel_status.append(
                    ChannelStatus(name="email", enabled=False, connected=False)
                )
                logger.info("email channel: disabled")
    finally:
        for conn in mcp_connections:
            await conn.close()


async def _run_onboard(config_path: Path) -> None:
    """Interactive setup wizard."""
    print("squidbot setup wizard")
    print("=" * 40)
    api_base = input("LLM API base URL [https://openrouter.ai/api/v1]: ").strip()
    api_key = input("API key: ").strip()
    model_id = input("Model identifier [anthropic/claude-opus-4-5]: ").strip()

    from squidbot.config.schema import (  # noqa: PLC0415
        LLMModelConfig,
        LLMPoolEntry,
        LLMProviderConfig,
    )

    settings = Settings()
    settings.llm.providers["default"] = LLMProviderConfig(
        api_base=api_base or "https://openrouter.ai/api/v1",
        api_key=api_key,
    )
    settings.llm.models["default"] = LLMModelConfig(
        provider="default",
        model=model_id or "anthropic/claude-opus-4-5",
    )
    settings.llm.pools["default"] = [LLMPoolEntry(model="default")]
    settings.llm.default_pool = "default"

    settings.save(config_path)
    print(f"\nConfiguration saved to {config_path}")
    print("Run 'squidbot agent' to start chatting!")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
