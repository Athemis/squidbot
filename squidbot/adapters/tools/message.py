"""Tool for explicit message delivery and routed sends across channels."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from squidbot.config.schema import OwnerAliasEntry
from squidbot.core.models import OutboundMessage, Session, ToolDefinition, ToolResult

if TYPE_CHECKING:
    from squidbot.core.ports import ChannelPort


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_EXPLICIT_EMAIL_PATTERNS = [
    re.compile(r"\bper\s+e-?mail\b", re.IGNORECASE),
    re.compile(r"\bvia\s+e-?mail\b", re.IGNORECASE),
    re.compile(r"\bsend\b.*\be-?mail\b", re.IGNORECASE),
    re.compile(r"\bschick\w*\b.*\be-?mail\b", re.IGNORECASE),
]
_EXPLICIT_MATRIX_PATTERNS = [
    re.compile(r"\bsend\b.*\bmatrix\b", re.IGNORECASE),
    re.compile(r"\bschick\w*\b.*\bmatrix\b", re.IGNORECASE),
]
_NEGATIVE_PATTERNS = [
    re.compile(r"\bdo\s+not\s+send\b", re.IGNORECASE),
    re.compile(r"\bdon't\s+send\b", re.IGNORECASE),
    re.compile(r"\bnicht\s+schick\w*\b", re.IGNORECASE),
]


def _resolve_safe(workspace: Path, path: str, restrict: bool) -> Path | None:
    workspace_resolved = workspace.resolve()
    resolved = (
        (workspace / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    )
    if restrict and not str(resolved).startswith(str(workspace_resolved)):
        return None
    return resolved


def _is_owner_sender(sender_id: str, channel: str, aliases: list[OwnerAliasEntry]) -> bool:
    return any(alias.channel == channel and alias.address == sender_id for alias in aliases) or any(
        alias.channel is None and alias.address == sender_id for alias in aliases
    )


def _is_email_like(value: str) -> bool:
    return bool(_EMAIL_RE.match(value))


def _is_explicit_routing_request(
    text: str, target_channel: str, target_sender_id: str | None
) -> bool:
    if any(pattern.search(text) for pattern in _NEGATIVE_PATTERNS):
        return False

    patterns = _EXPLICIT_EMAIL_PATTERNS if target_channel == "email" else _EXPLICIT_MATRIX_PATTERNS
    return any(pattern.search(text) for pattern in patterns) or bool(
        target_sender_id and target_sender_id in text
    )


def _is_supported_route(source_channel: str, target_channel: str, sender_override: bool) -> bool:
    if source_channel == target_channel:
        return not sender_override
    return source_channel == "matrix" and target_channel == "email"


class MessageTool:
    """Send explicit messages in the current or another supported channel."""

    name = "message"
    description = (
        "Send a message with optional file attachments. "
        "Use target_channel and target_sender_id only for explicit owner-approved routing."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Message text to send."},
            "attachments": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Local file paths to attach.",
            },
            "target_channel": {
                "type": "string",
                "description": "Optional target channel (default: current channel).",
            },
            "target_sender_id": {
                "type": "string",
                "description": "Optional target recipient id (default: current sender).",
            },
        },
        "required": ["content"],
    }

    def __init__(
        self,
        *,
        channel_registry: dict[str, ChannelPort],
        current_session: Session,
        inbound_text: str,
        owner_aliases: list[OwnerAliasEntry],
        outbound_metadata: dict[str, Any],
        workspace: Path,
        restrict_to_workspace: bool,
    ) -> None:
        self._channel_registry = channel_registry
        self._current_session = current_session
        self._inbound_text = inbound_text
        self._owner_aliases = owner_aliases
        self._outbound_metadata = outbound_metadata
        self._workspace = workspace
        self._restrict_to_workspace = restrict_to_workspace

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        content_raw = kwargs.get("content")
        if not isinstance(content_raw, str) or not content_raw:
            return ToolResult(tool_call_id="", content="Error: content is required", is_error=True)

        attachments_raw = kwargs.get("attachments", [])
        if not isinstance(attachments_raw, list):
            return ToolResult(
                tool_call_id="", content="Error: attachments must be a list", is_error=True
            )

        target_channel_raw = kwargs.get("target_channel")
        target_channel = self._current_session.channel
        if isinstance(target_channel_raw, str) and target_channel_raw:
            target_channel = target_channel_raw
        if target_channel not in self._channel_registry:
            return ToolResult(
                tool_call_id="", content="Error: target channel unavailable", is_error=True
            )

        target_sender_raw = kwargs.get("target_sender_id")
        target_sender = (
            target_sender_raw if isinstance(target_sender_raw, str) and target_sender_raw else None
        )

        sender_override = (
            target_sender is not None and target_sender != self._current_session.sender_id
        )
        routed = target_channel != self._current_session.channel or sender_override

        if routed:
            is_owner = _is_owner_sender(
                self._current_session.sender_id,
                self._current_session.channel,
                self._owner_aliases,
            )
            if not is_owner:
                return ToolResult(
                    tool_call_id="",
                    content="Error: routed send requires owner",
                    is_error=True,
                )
            if not _is_explicit_routing_request(self._inbound_text, target_channel, target_sender):
                return ToolResult(
                    tool_call_id="",
                    content="Error: explicit routing instruction required",
                    is_error=True,
                )

        resolved_sender = self._resolve_target_sender(target_channel, target_sender)
        if resolved_sender is None:
            return ToolResult(
                tool_call_id="",
                content="Error: target recipient could not be resolved",
                is_error=True,
            )

        sender_override = resolved_sender != self._current_session.sender_id
        if not _is_supported_route(self._current_session.channel, target_channel, sender_override):
            return ToolResult(
                tool_call_id="", content="Error: target route is not supported", is_error=True
            )

        outbound_metadata = dict(self._outbound_metadata)
        if target_channel == "matrix":
            room_id = outbound_metadata.get("matrix_room_id")
            if not isinstance(room_id, str) or not room_id:
                return ToolResult(
                    tool_call_id="",
                    content="Error: target recipient could not be resolved",
                    is_error=True,
                )

        attachments: list[Path] = []
        for raw in attachments_raw:
            if not isinstance(raw, str):
                return ToolResult(
                    tool_call_id="",
                    content="Error: attachment path must be a string",
                    is_error=True,
                )
            path = raw.strip()
            if not path:
                continue
            resolved = _resolve_safe(self._workspace, path, self._restrict_to_workspace)
            if resolved is None:
                return ToolResult(
                    tool_call_id="",
                    content="Error: attachment path is outside workspace",
                    is_error=True,
                )
            if not await asyncio.to_thread(resolved.exists):
                return ToolResult(
                    tool_call_id="",
                    content=f"Error: attachment does not exist: {path}",
                    is_error=True,
                )
            if not await asyncio.to_thread(resolved.is_file):
                return ToolResult(
                    tool_call_id="",
                    content=f"Error: attachment is not a file: {path}",
                    is_error=True,
                )
            attachments.append(resolved)

        outbound = OutboundMessage(
            session=Session(channel=target_channel, sender_id=resolved_sender),
            text=content_raw,
            attachment=attachments,
            metadata=outbound_metadata,
        )

        try:
            await self._channel_registry[target_channel].send(outbound)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_call_id="",
                content=f"Error: failed to send message: {exc}",
                is_error=True,
            )

        logger.info(
            "message tool routed send: source={} target={} sender={} attachments={}",
            self._current_session.channel,
            target_channel,
            resolved_sender,
            len(attachments),
        )
        return ToolResult(
            tool_call_id="",
            content=(
                f"Message sent to {target_channel}:{resolved_sender} "
                f"with {len(attachments)} attachment(s)"
            ),
        )

    def _resolve_target_sender(
        self, target_channel: str, target_sender_id: str | None
    ) -> str | None:
        if target_sender_id is not None:
            return target_sender_id

        if target_channel == self._current_session.channel:
            return self._current_session.sender_id

        if target_channel != "email":
            return None

        candidates = [
            alias.address
            for alias in self._owner_aliases
            if alias.channel == "email" and _is_email_like(alias.address)
        ]
        if not candidates:
            candidates = [
                alias.address
                for alias in self._owner_aliases
                if alias.channel is None and _is_email_like(alias.address)
            ]

        if len(candidates) == 1:
            return candidates[0]

        return None
