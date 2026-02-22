"""
Sub-agent spawn tools for squidbot.

Provides CollectingChannel (internal), SubAgentFactory, JobStore, SpawnTool,
and SpawnAwaitTool. Enables a parent agent to delegate tasks to isolated
sub-agents running as concurrent asyncio Tasks, optionally configured via
named profiles in squidbot.yaml.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from squidbot.config.schema import SpawnProfile
from squidbot.core.agent import AgentLoop
from squidbot.core.memory import MemoryManager
from squidbot.core.models import (
    InboundMessage,
    OutboundMessage,
    Session,
    ToolDefinition,
    ToolResult,
)
from squidbot.core.ports import LLMPort
from squidbot.core.registry import ToolRegistry


class CollectingChannel:
    """
    Non-streaming channel used by sub-agents to collect their output.

    Sub-agents write their final response via send(); the result is
    retrieved via the collected_text property.
    """

    streaming: bool = False

    def __init__(self) -> None:
        """Initialise with empty buffer."""
        self._parts: list[str] = []

    async def send(self, message: OutboundMessage) -> None:
        """Append message text to the internal buffer."""
        self._parts.append(message.text)

    async def send_typing(self, session_id: str) -> None:
        """No-op — sub-agents do not send typing indicators."""

    def receive(self) -> AsyncIterator[InboundMessage]:
        """Return an async iterator that immediately exhausts."""
        return _empty_iter()

    @property
    def collected_text(self) -> str:
        """Return all collected text joined."""
        return "".join(self._parts)


async def _empty_iter() -> AsyncIterator[InboundMessage]:
    """Async generator that yields nothing."""
    return
    yield  # makes this an async generator


class JobStore:
    """
    In-memory registry of background sub-agent asyncio Tasks.

    Each job is started as an asyncio.Task and stored by a caller-assigned ID.
    Results (or exceptions) are available via await_jobs().
    """

    def __init__(self) -> None:
        """Initialise with an empty task dict."""
        self._tasks: dict[str, asyncio.Task[str]] = {}

    def start(self, job_id: str, coro: Any) -> None:
        """
        Schedule a coroutine as a background asyncio Task.

        Args:
            job_id: Unique identifier for this job.
            coro: Coroutine to run.
        """
        self._tasks[job_id] = asyncio.create_task(coro)

    async def await_jobs(self, job_ids: list[str]) -> dict[str, str | BaseException]:
        """
        Wait for the specified jobs and return their results.

        Args:
            job_ids: Job IDs to wait for. Unknown IDs are silently omitted.

        Returns:
            Dict mapping job_id to result string or captured exception.
        """
        known = {jid: self._tasks[jid] for jid in job_ids if jid in self._tasks}
        if not known:
            return {}
        outcomes = await asyncio.gather(*known.values(), return_exceptions=True)
        return dict(zip(known.keys(), outcomes, strict=True))

    def all_job_ids(self) -> list[str]:
        """Return all registered job IDs."""
        return list(self._tasks.keys())


_SPAWN_TOOL_NAMES = {"spawn", "spawn_await"}


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


class SubAgentFactory:
    """
    Builds fresh AgentLoop instances for sub-agents.

    Each sub-agent gets its own registry (filtered copy of the parent's)
    and optionally a different system prompt. spawn/spawn_await are always
    excluded from sub-agent registries to prevent runaway nesting.

    Pool resolution is handled by the injected resolve_llm callable, allowing
    each sub-agent profile to use a different LLM pool.
    """

    def __init__(
        self,
        memory: MemoryManager,
        registry: ToolRegistry,
        workspace: Path,
        default_bootstrap_files: list[str],
        profiles: dict[str, SpawnProfile],
        default_pool: str,
        resolve_llm: Callable[[str], LLMPort],
    ) -> None:
        """
        Args:
            memory: Memory manager shared with parent.
            registry: Parent's tool registry (source for sub-agent tools).
            workspace: Path to the agent workspace directory for loading bootstrap files.
            default_bootstrap_files: Ordered list of filenames to load when no profile overrides.
            profiles: Named sub-agent profiles from config.
            default_pool: Name of the LLM pool to use when no profile pool is set.
            resolve_llm: Callable that resolves a pool name to an LLMPort adapter.
        """
        self._memory = memory
        self._registry = registry
        self._workspace = workspace
        self._default_bootstrap_files = default_bootstrap_files
        self._profiles = profiles
        self._default_pool = default_pool
        self._resolve_llm = resolve_llm

    def build(
        self,
        system_prompt_override: str | None,
        tools_filter: list[str] | None,
        profile_name: str | None = None,
    ) -> AgentLoop:
        """
        Build a fresh AgentLoop for a sub-agent.

        Args:
            system_prompt_override: If set, replaces the parent system prompt.
            tools_filter: If set, only these tool names are available.
                          spawn/spawn_await are always excluded regardless.
            profile_name: Named profile to use for pool and tool configuration.

        Returns:
            A new AgentLoop with an isolated tool registry.
        """
        profile = self._profiles.get(profile_name) if profile_name else None
        pool = (profile.pool if profile and profile.pool else None) or self._default_pool
        llm = self._resolve_llm(pool)

        # Assemble system prompt: bootstrap files → system_prompt_file → inline
        bootstrap_files = (
            profile.bootstrap_files
            if (profile and profile.bootstrap_files)
            else self._default_bootstrap_files
        )
        prompt_parts: list[str] = []
        if bootstrap_files:
            base = _load_bootstrap_prompt(self._workspace, bootstrap_files)
            prompt_parts.append(base)

        if profile and profile.system_prompt_file:
            file_path = self._workspace / profile.system_prompt_file
            if file_path.exists():
                prompt_parts.append(file_path.read_text(encoding="utf-8"))

        inline = system_prompt_override or (profile.system_prompt if profile else "")
        if inline:
            prompt_parts.append(inline)

        child_prompt = (
            "\n\n---\n\n".join(prompt_parts) or "You are a helpful personal AI assistant."
        )

        child_registry = ToolRegistry()
        for tool in self._registry._tools.values():
            if tool.name in _SPAWN_TOOL_NAMES:
                continue
            if tools_filter is not None and tool.name not in tools_filter:
                continue
            child_registry.register(tool)

        return AgentLoop(
            llm=llm,
            memory=self._memory,
            registry=child_registry,
            system_prompt=child_prompt,
        )


class SpawnTool:
    """
    Starts a sub-agent as a background asyncio Task.

    Returns a job_id immediately without waiting for completion.
    Use spawn_await to retrieve results.
    """

    name = "spawn"
    description = (
        "Delegate a task to an isolated sub-agent running in the background. "
        "Returns a job_id immediately. Use spawn_await to collect the result. "
        "Multiple sub-agents can run in parallel."
    )

    def __init__(self, factory: SubAgentFactory, job_store: JobStore) -> None:
        """
        Args:
            factory: Builds child AgentLoop instances.
            job_store: Stores running jobs by ID.
        """
        self._factory = factory
        self._job_store = job_store
        self.parameters: dict[str, Any] = self._build_parameters()

    def _build_parameters(self) -> dict[str, Any]:
        """Build tool parameter schema (profile enum from configured profiles)."""
        profile_prop: dict[str, Any] = {
            "type": "string",
            "description": "Named sub-agent profile. Omit to inherit parent context.",
        }
        profile_names = list(self._factory._profiles.keys())
        if profile_names:
            profile_prop["enum"] = profile_names

        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task for the sub-agent to complete.",
                },
                "profile": profile_prop,
                "context": {
                    "type": "string",
                    "description": "Additional context prepended to the task.",
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Override the sub-agent's system prompt.",
                },
                "tools": {
                    "type": "string",
                    "description": "Comma-separated tool whitelist. Overrides profile tools.",
                },
            },
            "required": ["task"],
        }

    def to_definition(self) -> ToolDefinition:
        """Return a ToolDefinition with the dynamic parameter schema."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Start a sub-agent task asynchronously.

        Args:
            **kwargs: task (required), profile, context, system_prompt, tools.

        Returns:
            ToolResult with job_id on success, or is_error=True on validation failure.
        """
        task_raw = kwargs.get("task")
        if not isinstance(task_raw, str) or not task_raw.strip():
            return ToolResult(tool_call_id="", content="Error: task is required", is_error=True)
        task: str = task_raw.strip()

        profile_name: str | None = (
            kwargs.get("profile") if isinstance(kwargs.get("profile"), str) else None
        )
        context: str | None = (
            kwargs.get("context") if isinstance(kwargs.get("context"), str) else None
        )
        system_prompt_override: str | None = (
            kwargs.get("system_prompt") if isinstance(kwargs.get("system_prompt"), str) else None
        )
        tools_raw: str | None = (
            kwargs.get("tools") if isinstance(kwargs.get("tools"), str) else None
        )

        # Resolve profile
        resolved_system_prompt = system_prompt_override
        tools_filter: list[str] | None = None

        if profile_name is not None:
            profile = self._factory._profiles.get(profile_name)
            if profile is None:
                return ToolResult(
                    tool_call_id="",
                    content=f"Error: unknown profile '{profile_name}'",
                    is_error=True,
                )
            if profile.tools:
                tools_filter = profile.tools

        # Explicit tools param overrides profile
        if tools_raw:
            tools_filter = [t.strip() for t in tools_raw.split(",") if t.strip()]

        user_message = f"{context}\n\n{task}".strip() if context else task

        job_id = uuid.uuid4().hex[:8]
        agent_loop = self._factory.build(
            system_prompt_override=resolved_system_prompt,
            tools_filter=tools_filter,
            profile_name=profile_name,
        )
        channel = CollectingChannel()
        session = Session(channel="spawn", sender_id=job_id)

        async def _run() -> str:
            await agent_loop.run(session=session, user_message=user_message, channel=channel)
            return channel.collected_text

        self._job_store.start(job_id, _run())
        return ToolResult(tool_call_id="", content=job_id)


class SpawnAwaitTool:
    """
    Waits for one or more background sub-agent jobs and returns their results.

    Always returns is_error=False. Individual job failures are embedded in
    the content as [job_id: ERROR] markers so the parent sees all results.
    """

    name = "spawn_await"
    description = (
        "Wait for background sub-agent jobs to complete and retrieve their results. "
        "Pass a comma-separated list of job IDs, or '*' to wait for all pending jobs."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "job_ids": {
                "type": "string",
                "description": "Comma-separated job IDs to wait for, or '*' for all.",
            },
        },
        "required": ["job_ids"],
    }

    def __init__(self, job_store: JobStore) -> None:
        """
        Args:
            job_store: The shared job store from SpawnTool.
        """
        self._job_store = job_store

    def to_definition(self) -> ToolDefinition:
        """Return a ToolDefinition."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Wait for jobs and format results.

        Args:
            **kwargs: job_ids (required) — comma-separated IDs or '*'.

        Returns:
            ToolResult with all job results embedded. Never is_error=True
            unless job_ids is missing.
        """
        job_ids_raw = kwargs.get("job_ids")
        if not isinstance(job_ids_raw, str) or not job_ids_raw.strip():
            return ToolResult(tool_call_id="", content="Error: job_ids is required", is_error=True)

        if job_ids_raw.strip() == "*":
            ids = self._job_store.all_job_ids()
            if not ids:
                return ToolResult(tool_call_id="", content="No jobs found.")
        else:
            ids = [i.strip() for i in job_ids_raw.split(",") if i.strip()]

        results = await self._job_store.await_jobs(ids)

        parts: list[str] = []
        for jid in ids:
            if jid not in results:
                parts.append(f"[{jid}: NOT FOUND]")
            elif isinstance(results[jid], BaseException):
                parts.append(f"[{jid}: ERROR]\n{results[jid]}")
            else:
                parts.append(f"[{jid}: OK]\n{results[jid]}")

        return ToolResult(tool_call_id="", content="\n\n".join(parts))
