"""
Core data models for squidbot.

These are plain dataclasses with no external dependencies beyond the standard
library. They represent the domain concepts shared across the entire system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


@dataclass
class ToolCall:
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """The result of executing a tool."""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    """A single message in a conversation."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None  # set when role == "tool"
    reasoning_content: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    channel: str | None = None
    sender_id: str | None = None

    def to_openai_dict(self, *, include_reasoning_content: bool = False) -> dict[str, Any]:
        """Serialize to OpenAI API message format.

        Args:
            include_reasoning_content: When True, include reasoning_content if present.

        Returns:
            OpenAI-compatible message payload.
        """
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if include_reasoning_content and self.reasoning_content is not None:
            d["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": str(tc.arguments)},
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d


@dataclass
class Session:
    """A conversation session, identified by channel and sender."""

    channel: str
    sender_id: str
    created_at: datetime = field(default_factory=datetime.now, compare=False)

    @property
    def id(self) -> str:
        return f"{self.channel}:{self.sender_id}"


@dataclass
class InboundMessage:
    """A message received from a channel."""

    session: Session
    text: str
    received_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    """A message to be sent to a channel."""

    session: Session
    text: str
    attachment: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolDefinition:
    """Definition of a tool that can be called by the LLM."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object

    def to_openai_dict(self) -> dict[str, Any]:
        """Serialize to OpenAI API tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class CronJob:
    """A scheduled task."""

    id: str
    name: str
    message: str
    schedule: str  # cron expression ("0 9 * * *") or interval ("every 3600")
    channel: str  # target session ID, e.g. "cli:local" or "matrix:@user:matrix.org"
    enabled: bool = True
    timezone: str = "local"
    last_run: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionInfo:
    """Runtime metadata for a session seen since gateway start."""

    session_id: str
    channel: str
    sender_id: str
    started_at: datetime
    message_count: int


@dataclass
class ChannelStatus:
    """Runtime status of a channel adapter."""

    name: str
    enabled: bool
    connected: bool
    error: str | None = None
