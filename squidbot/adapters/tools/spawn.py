"""
Sub-agent spawn tools for squidbot.

Provides CollectingChannel (internal), SubAgentFactory, JobStore, SpawnTool,
and SpawnAwaitTool. Enables a parent agent to delegate tasks to isolated
sub-agents running as concurrent asyncio Tasks, optionally configured via
named profiles in squidbot.yaml.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from squidbot.config.schema import SpawnProfile
from squidbot.core.agent import AgentLoop
from squidbot.core.memory import MemoryManager
from squidbot.core.models import InboundMessage, OutboundMessage
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


class SubAgentFactory:
    """
    Builds fresh AgentLoop instances for sub-agents.

    Each sub-agent gets its own registry (filtered copy of the parent's)
    and optionally a different system prompt. spawn/spawn_await are always
    excluded from sub-agent registries to prevent runaway nesting.
    """

    def __init__(
        self,
        llm: LLMPort,
        memory: MemoryManager,
        registry: ToolRegistry,
        system_prompt: str,
        profiles: dict[str, SpawnProfile],
    ) -> None:
        """
        Args:
            llm: LLM adapter shared with parent.
            memory: Memory manager shared with parent.
            registry: Parent's tool registry (source for sub-agent tools).
            system_prompt: Parent's system prompt (default for sub-agents).
            profiles: Named sub-agent profiles from config.
        """
        self._llm = llm
        self._memory = memory
        self._registry = registry
        self._system_prompt = system_prompt
        self._profiles = profiles

    def build(
        self,
        system_prompt_override: str | None,
        tools_filter: list[str] | None,
    ) -> AgentLoop:
        """
        Build a fresh AgentLoop for a sub-agent.

        Args:
            system_prompt_override: If set, replaces the parent system prompt.
            tools_filter: If set, only these tool names are available.
                          spawn/spawn_await are always excluded regardless.

        Returns:
            A new AgentLoop with an isolated tool registry.
        """
        child_prompt = system_prompt_override or self._system_prompt

        child_registry = ToolRegistry()
        for tool in self._registry._tools.values():
            if tool.name in _SPAWN_TOOL_NAMES:
                continue
            if tools_filter is not None and tool.name not in tools_filter:
                continue
            child_registry.register(tool)

        return AgentLoop(
            llm=self._llm,
            memory=self._memory,
            registry=child_registry,
            system_prompt=child_prompt,
        )
