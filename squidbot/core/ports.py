"""
Port interfaces for squidbot.

These are Python Protocol classes defining the contracts that adapters must satisfy.
The core domain imports ONLY from this file (and models.py) for any external dependency.

Adapters implement these protocols without inheriting from them (structural subtyping).
mypy verifies conformance statically.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from squidbot.core.models import (
    ChannelStatus,
    CronJob,
    InboundMessage,
    Message,
    OutboundMessage,
    SessionInfo,
    ToolDefinition,
    ToolResult,
)
from squidbot.core.skills import SkillMetadata


class LLMPort(Protocol):
    """
    Interface for language model communication.

    The LLM adapter wraps any OpenAI-compatible API endpoint.
    Responses are streamed as text chunks; tool calls are accumulated and
    returned as a structured event.
    """

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        stream: bool = True,
    ) -> AsyncIterator[str | list[Any]]:
        """
        Send messages to the LLM and receive a response stream.

        Yields either:
        - str: a text chunk to be forwarded to the channel
        - list[ToolCall]: a complete set of tool calls (end of response)

        Args:
            messages: The full conversation history including system prompt.
            tools: Available tool definitions in OpenAI format.
            stream: Whether to stream the response (default True).
        """
        ...


class ChannelPort(Protocol):
    """
    Interface for inbound/outbound message channels.

    A channel adapter handles the specifics of a messaging platform:
    authentication, message format conversion, and delivery.

    The `streaming` attribute controls how the agent loop delivers responses:
    - True (e.g. CLI): send() is called per text chunk as it arrives from the LLM
    - False (e.g. Matrix, Email): chunks are accumulated and send() is called once
    """

    streaming: bool  # True = stream chunks; False = collect then send

    def receive(self) -> AsyncIterator[InboundMessage]:
        """Yield inbound messages as they arrive."""
        ...

    async def send(self, message: OutboundMessage) -> None:
        """Send a message to the channel."""
        ...

    async def send_typing(self, session_id: str) -> None:
        """
        Send a typing indicator if the channel supports it.

        Implementations that don't support typing indicators should no-op.
        """
        ...


class ToolPort(Protocol):
    """
    Interface for agent tools.

    Each tool exposes a name, description, and JSON Schema for its parameters.
    The agent loop calls execute() with parsed keyword arguments.
    """

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object describing accepted arguments

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute the tool with the given arguments.

        Args:
            **kwargs: Tool-specific arguments as defined in `parameters`.

        Returns:
            ToolResult with the output or error message.
        """
        ...


class MemoryPort(Protocol):
    """
    Interface for session state persistence.

    Manages:
    - Conversation history: global JSONL log of all messages across all channels
    - Global memory document: cross-session notes (MEMORY.md), written by the agent
    - Global summary: cross-channel auto-generated consolidation summary
    - Cron jobs: scheduled task definitions
    """

    async def load_history(self, last_n: int | None = None) -> list[Message]:
        """Load messages from global history. Returns last_n if specified, else all."""
        ...

    async def append_message(self, message: Message) -> None:
        """Append a single message to the global history."""
        ...

    async def load_global_memory(self) -> str:
        """Load the global cross-session memory document."""
        ...

    async def save_global_memory(self, content: str) -> None:
        """Overwrite the global memory document."""
        ...

    async def load_global_summary(self) -> str:
        """Load the auto-generated global consolidation summary."""
        ...

    async def save_global_summary(self, content: str) -> None:
        """Overwrite the global consolidation summary."""
        ...

    async def load_global_cursor(self) -> int:
        """Return the last consolidated message index (0 if none)."""
        ...

    async def save_global_cursor(self, cursor: int) -> None:
        """Persist the consolidation cursor."""
        ...

    async def load_cron_jobs(self) -> list[CronJob]:
        """Load all scheduled jobs."""
        ...

    async def save_cron_jobs(self, jobs: list[CronJob]) -> None:
        """Persist the full list of scheduled jobs."""
        ...


class SkillsPort(Protocol):
    """
    Interface for skill discovery and loading.

    Implementations search one or more directories for SKILL.md files,
    parse their frontmatter, and cache results keyed by (path, mtime).
    """

    def list_skills(self) -> list[SkillMetadata]:
        """
        Return all discovered SkillMetadata objects.

        Re-reads from disk only if a file's mtime has changed since last load.
        """
        ...

    def load_skill_body(self, name: str) -> str:
        """Return the full SKILL.md text for a named skill."""
        ...


class StatusPort(Protocol):
    """
    Interface for gateway status reporting.

    Provides read-only access to runtime state for dashboards or status commands.
    Implementations hold a GatewayState snapshot updated by running components.
    """

    def get_active_sessions(self) -> list[SessionInfo]:
        """Return metadata for all sessions seen since gateway start."""
        ...

    def get_channel_status(self) -> list[ChannelStatus]:
        """Return runtime status of all configured channels."""
        ...

    def get_cron_jobs(self) -> list[CronJob]:
        """Return the current list of scheduled jobs."""
        ...

    def get_skills(self) -> list[SkillMetadata]:
        """Return all discovered skills with availability info."""
        ...
