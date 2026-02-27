"""Gateway runner for squidbot.

This module contains the gateway process that runs all enabled channels
concurrently, along with supporting state management classes.
"""

from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.adapters.tools.mcp import McpConnectionProtocol
    from squidbot.config.schema import Settings
    from squidbot.core.agent import AgentLoop
    from squidbot.core.heartbeat import LastChannelTracker
    from squidbot.core.models import ChannelStatus, CronJob, SessionInfo
    from squidbot.core.ports import ChannelPort, LLMPort
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


async def _channel_loop_with_state(
    channel: ChannelPort,
    loop: Any,
    state: GatewayState,
    storage: JsonlMemory,
    tracker: LastChannelTracker | None = None,
) -> None:
    """
    Drive a single channel and update GatewayState on each message.

    Creates a SessionInfo entry on first message from a session, then increments
    message_count on subsequent messages.

    Args:
        channel: The channel adapter to drive.
        loop: The agent loop to handle each message.
        state: Live gateway state — updated in-place.
        storage: Persistence adapter used to construct MemoryWriteTool per message.
        tracker: Optional tracker receiving the latest channel/session/metadata.
    """
    from squidbot.adapters.tools.cron import build_context_cron_tools  # noqa: PLC0415
    from squidbot.adapters.tools.memory_write import MemoryWriteTool  # noqa: PLC0415
    from squidbot.core.models import SessionInfo  # noqa: PLC0415

    async for inbound in channel.receive():
        if tracker is not None:
            tracker.update(channel, inbound.session, inbound.metadata)
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
        extra = [
            MemoryWriteTool(storage=storage),
            *build_context_cron_tools(
                storage=storage,
                default_channel=inbound.session.id,
                default_metadata=inbound.metadata,
            ),
        ]
        await loop.run(
            inbound.session,
            inbound.text,
            channel,
            extra_tools=extra,
            outbound_metadata=inbound.metadata,
        )


async def _channel_loop(
    channel: ChannelPort,
    loop: Any,
    storage: JsonlMemory,
    tracker: LastChannelTracker | None = None,
) -> None:
    """
    Drive a single channel without state tracking (used by agent command).

    Args:
        channel: The channel adapter to drive.
        loop: The agent loop to handle each message.
        storage: Persistence adapter used to construct MemoryWriteTool per message.
        tracker: Optional tracker receiving the latest channel/session/metadata.
    """
    from squidbot.adapters.tools.cron import build_context_cron_tools  # noqa: PLC0415
    from squidbot.adapters.tools.memory_write import MemoryWriteTool  # noqa: PLC0415

    async for inbound in channel.receive():
        if tracker is not None:
            tracker.update(channel, inbound.session, inbound.metadata)
        extra = [
            MemoryWriteTool(storage=storage),
            *build_context_cron_tools(
                storage=storage,
                default_channel=inbound.session.id,
                default_metadata=inbound.metadata,
            ),
        ]
        await loop.run(
            inbound.session,
            inbound.text,
            channel,
            extra_tools=extra,
            outbound_metadata=inbound.metadata,
        )


def _resolve_llm(settings: Settings, pool_name: str) -> LLMPort:
    """
    Construct an OpenAIAdapter from the new provider/model/pool schema.

    Resolves the named pool to its model entries, then looks up the model and
    provider configuration to obtain API credentials and model ID. Raises
    ValueError if any referenced pool, model, or provider is missing from
    the configuration.

    Args:
        settings: Loaded application settings.
        pool_name: Name of the LLM pool to resolve (e.g. "default").

    Returns:
        An LLMPort-compatible adapter for the first entry in the pool.

    Raises:
        ValueError: If the pool, model, or provider is not found in settings.
    """
    from squidbot.adapters.llm.openai import OpenAIAdapter  # noqa: PLC0415

    pool_entries = settings.llm.pools.get(pool_name)
    if not pool_entries:
        raise ValueError(f"LLM pool '{pool_name}' not found in config")

    adapters: list[OpenAIAdapter] = []
    for entry in pool_entries:
        model_cfg = settings.llm.models.get(entry.model)
        if not model_cfg:
            raise ValueError(f"LLM model '{entry.model}' not found in llm.models")
        provider_cfg = settings.llm.providers.get(model_cfg.provider)
        if not provider_cfg:
            raise ValueError(f"LLM provider '{model_cfg.provider}' not found in llm.providers")
        adapters.append(
            OpenAIAdapter(
                api_base=provider_cfg.api_base,
                api_key=provider_cfg.api_key,
                model=model_cfg.model,
            )
        )

    if len(adapters) == 1:
        return adapters[0]
    from squidbot.adapters.llm.pool import PooledLLMAdapter  # noqa: PLC0415

    return PooledLLMAdapter(adapters)


# Bootstrap file constants used by gateway
BOOTSTRAP_FILES_MAIN: list[str] = [
    "SOUL.md",
    "IDENTITY.md",
    "USER.md",
    "AGENTS.md",
    "ENVIRONMENT.md",
    "BOOTSTRAP.md",  # loaded last if present; self-deletes after first-run interview
]
BOOTSTRAP_FILES_SUBAGENT: list[str] = ["AGENTS.md", "ENVIRONMENT.md"]


def _load_bootstrap_prompt(workspace: Path, filenames: list[str]) -> str:
    """
    Load and concatenate bootstrap files from the workspace.

    Missing files are silently skipped. Returns a fallback string if no
    files are found.

    Args:
        workspace: Path to the agent workspace directory.
        filenames: Ordered list of filenames to load.

    Returns:
        Concatenated prompt text, separated by horizontal rules.
    """
    parts: list[str] = []
    for name in filenames:
        file_path = workspace / name
        if file_path.exists():
            parts.append(file_path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts) if parts else "You are a helpful personal AI assistant."


async def _make_agent_loop(
    settings: Settings,
    storage_dir: Path | None = None,
) -> tuple[AgentLoop, list[McpConnectionProtocol], JsonlMemory]:
    """
    Construct the agent loop from configuration.

    Args:
        settings: Loaded application settings.
        storage_dir: Override the storage directory. Defaults to ~/.squidbot.

    Returns:
        Tuple of (agent_loop, mcp_connections, storage). Callers must close
        mcp_connections on shutdown by calling conn.close() on each.
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

    # LLM adapter — resolved from pool/model/provider schema
    llm = _resolve_llm(settings, settings.llm.default_pool)

    memory = MemoryManager(
        storage=storage,
        skills=skills,
        owner_aliases=list(settings.owner.aliases),
        history_context_messages=settings.agents.history_context_messages,
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

    if settings.tools.fetch_url.enabled:
        from squidbot.adapters.tools.fetch_url import FetchUrlTool  # noqa: PLC0415

        registry.register(FetchUrlTool())

    from squidbot.adapters.tools.cron import build_global_cron_tools  # noqa: PLC0415

    for cron_tool in build_global_cron_tools(storage=storage):
        registry.register(cron_tool)

    if settings.tools.search_history.enabled:
        from squidbot.adapters.tools.search_history import SearchHistoryTool  # noqa: PLC0415

        registry.register(SearchHistoryTool(base_dir=_storage_dir))

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

    system_prompt = _load_bootstrap_prompt(workspace, BOOTSTRAP_FILES_MAIN)

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
            memory=memory,
            registry=registry,
            workspace=workspace,
            default_bootstrap_files=BOOTSTRAP_FILES_SUBAGENT,
            profiles=settings.tools.spawn.profiles,
            default_pool=settings.llm.default_pool,
            resolve_llm=functools.partial(_resolve_llm, settings),
        )
        job_store = JobStore()
        registry.register(SpawnTool(factory=spawn_factory, job_store=job_store))
        registry.register(SpawnAwaitTool(job_store=job_store))

    return agent_loop, mcp_connections, storage


def _print_banner(settings: Any) -> None:
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


async def _run_gateway(config_path: Path) -> None:
    """Start all enabled channels concurrently.

    The gateway does not start a CLI channel — use `squidbot agent` for
    interactive terminal use. Log output goes to stderr; control the bot
    via Matrix or Email.
    """
    from loguru import logger  # noqa: PLC0415

    from squidbot.config.schema import Settings  # noqa: PLC0415
    from squidbot.core.heartbeat import HeartbeatService, LastChannelTracker  # noqa: PLC0415
    from squidbot.core.models import ChannelStatus, Session  # noqa: PLC0415
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

    agent_loop, mcp_connections, storage = await _make_agent_loop(settings)
    cron_jobs = await storage.load_cron_jobs()
    logger.info("cron: {} jobs loaded", len(cron_jobs))
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
    channel_registry: dict[str, ChannelPort] = {}

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
        from squidbot.adapters.tools.memory_write import MemoryWriteTool  # noqa: PLC0415

        extra = [MemoryWriteTool(storage=storage)]
        await agent_loop.run(
            session,
            job.message,
            ch,
            extra_tools=extra,
            outbound_metadata=job.metadata,
        )

    scheduler = CronScheduler(storage=storage)
    hb_pool = settings.agents.heartbeat.pool or settings.llm.default_pool
    hb_llm = _resolve_llm(settings, hb_pool) if hb_pool != settings.llm.default_pool else None
    from squidbot.adapters.tools.memory_write import MemoryWriteTool  # noqa: PLC0415

    def _hb_extra_tools(session_id: str) -> list[Any]:
        return [MemoryWriteTool(storage=storage)]

    heartbeat = HeartbeatService(
        agent_loop=agent_loop,
        tracker=tracker,
        workspace=workspace,
        config=settings.agents.heartbeat,
        llm_override=hb_llm,
        extra_tools_factory=_hb_extra_tools,
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
                tg.create_task(
                    _channel_loop_with_state(matrix_ch, agent_loop, state, storage, tracker=tracker)
                )
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
                tg.create_task(
                    _channel_loop_with_state(email_ch, agent_loop, state, storage, tracker=tracker)
                )
            else:
                state.channel_status.append(
                    ChannelStatus(name="email", enabled=False, connected=False)
                )
                logger.info("email channel: disabled")
    finally:
        for conn in mcp_connections:
            await conn.close()
