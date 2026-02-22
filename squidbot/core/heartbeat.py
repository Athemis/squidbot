"""
Heartbeat scheduling and content analysis utilities for squidbot.

Provides periodic autonomous agent wake-ups. Every N minutes the agent reads
HEARTBEAT.md from the workspace, checks for outstanding tasks, and delivers
alerts to the last active channel. HEARTBEAT_OK responses are silently dropped.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from squidbot.config.schema import HeartbeatConfig
from squidbot.core.agent import AgentLoop
from squidbot.core.models import Session
from squidbot.core.ports import ChannelPort

HEARTBEAT_OK_TOKEN = "HEARTBEAT_OK"

DEFAULT_HEARTBEAT_PROMPT = (
    "Read HEARTBEAT.md if it exists in your workspace. "
    "Follow any instructions strictly. Do not repeat tasks from prior turns. "
    "If nothing needs attention, reply with just: HEARTBEAT_OK"
)

# Bare unchecked checkboxes with no task text — treated as empty placeholders
_EMPTY_CHECKBOX_PATTERNS = {"- [ ]", "* [ ]"}


def _is_heartbeat_empty(content: str | None) -> bool:
    """
    Return True if HEARTBEAT.md has no actionable content.

    Skips blank lines, Markdown headings, HTML comments (single-line only,
    e.g. ``<!-- placeholder -->``), bare empty checkboxes, and completed
    checkboxes (``[x]`` / ``[X]``) regardless of trailing text.

    Args:
        content: The file content, or None if the file was absent.

    Returns:
        True if there is nothing actionable; False if any actionable line exists.
    """
    if not content:
        return True
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("<!--"):  # single-line HTML comments only
            continue
        if line in _EMPTY_CHECKBOX_PATTERNS:
            continue
        # Checked checkboxes (with or without trailing text) are non-actionable
        if line.startswith(("- [x]", "* [x]", "- [X]", "* [X]")):
            continue
        return False
    return True


class LastChannelTracker:
    """
    Tracks the most recently active channel and session.

    Updated by the gateway on every inbound message. Read by HeartbeatService
    when determining where to deliver alerts.
    """

    def __init__(self) -> None:
        self.channel: ChannelPort | None = None
        self.session: Session | None = None

    def update(self, channel: ChannelPort, session: Session) -> None:
        """
        Record the channel and session of the most recent inbound message.

        Args:
            channel: The channel the message arrived on.
            session: The session (channel type + sender ID) of the message.
        """
        self.channel = channel
        self.session = session


class _SinkChannel:
    """Internal channel that captures agent responses without delivering them."""

    streaming = False
    collected: str

    def __init__(self) -> None:
        self.collected = ""

    async def receive(self) -> AsyncIterator[object]:
        return
        yield  # noqa: B901

    async def send(self, message: object) -> None:
        from squidbot.core.models import OutboundMessage  # noqa: PLC0415

        if isinstance(message, OutboundMessage):
            self.collected = message.text

    async def send_typing(self, session_id: str) -> None:
        pass


class HeartbeatService:
    """
    Periodic heartbeat service for the squidbot gateway.

    Wakes the agent every interval_minutes, reads HEARTBEAT.md from the
    workspace, and delivers any alerts to the last active channel.
    HEARTBEAT_OK responses are silently dropped.
    """

    def __init__(
        self,
        agent_loop: AgentLoop,
        tracker: LastChannelTracker,
        workspace: Path,
        config: HeartbeatConfig,
    ) -> None:
        """
        Args:
            agent_loop: The shared agent loop to invoke on each tick.
            tracker: Tracks the last active channel and session.
            workspace: Path to the agent workspace (for HEARTBEAT.md).
            config: Heartbeat configuration.
        """
        self._agent_loop = agent_loop
        self._tracker = tracker
        self._workspace = workspace
        self._config = config

    def _is_in_active_hours(self, now: datetime | None = None) -> bool:
        """
        Return True if the current time is within the configured active window.

        Args:
            now: The current time. Defaults to datetime.now() if not provided.

        Returns:
            True if inside the active window; False otherwise.
        """
        if now is None:
            now = datetime.now()

        tz_name = self._config.timezone
        if tz_name == "local":
            local_now = now.astimezone()
        else:
            try:
                local_now = now.astimezone(ZoneInfo(tz_name))
            except ZoneInfoNotFoundError, KeyError:
                logger.warning("heartbeat: unknown timezone %r, falling back to local", tz_name)
                local_now = now.astimezone()

        start_h, start_m = (int(x) for x in self._config.active_hours_start.split(":"))
        end_h, end_m = (int(x) for x in self._config.active_hours_end.split(":"))

        # Zero-width window: always outside
        if (start_h, start_m) == (end_h, end_m):
            return False

        current_minutes = local_now.hour * 60 + local_now.minute
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m if not (end_h == 24 and end_m == 0) else 24 * 60

        return start_minutes <= current_minutes < end_minutes

    def _read_heartbeat_file(self) -> str | None:
        """
        Read HEARTBEAT.md from the workspace.

        Returns:
            File contents as a string, or None if the file does not exist.
        """
        path = self._workspace / "HEARTBEAT.md"
        try:
            return path.read_text(encoding="utf-8") if path.exists() else None
        except Exception:
            return None

    @staticmethod
    def _is_heartbeat_ok(text: str) -> bool:
        """
        Return True if the response is a HEARTBEAT_OK acknowledgment.

        HEARTBEAT_OK is recognized at the start or end of the reply (after strip).
        If it appears in the middle, the response is treated as an alert.

        Args:
            text: The agent's response text.

        Returns:
            True if the response should be silently dropped; False if it is an alert.
        """
        stripped = text.strip()
        return (
            stripped == HEARTBEAT_OK_TOKEN
            or stripped.startswith(HEARTBEAT_OK_TOKEN + "\n")
            or stripped.endswith("\n" + HEARTBEAT_OK_TOKEN)
        )

    async def _tick(self, now: datetime | None = None) -> None:
        """
        Execute a single heartbeat tick.

        Args:
            now: Current time (injectable for testing). Defaults to datetime.now().
        """
        # 1. Need an active session
        if self._tracker.channel is None or self._tracker.session is None:
            logger.debug("heartbeat: skipped (no active session)")
            return

        # 2. Active hours check
        if not self._is_in_active_hours(now=now):
            logger.debug("heartbeat: skipped (outside active hours)")
            return

        # 3. HEARTBEAT.md check — skip only when the file exists and is empty
        content = self._read_heartbeat_file()
        if content is not None and _is_heartbeat_empty(content):
            logger.debug("heartbeat: skipped (HEARTBEAT.md empty)")
            return

        # 4. Run agent into a sink channel
        sink = _SinkChannel()
        try:
            await self._agent_loop.run(
                self._tracker.session,
                self._config.prompt,
                sink,  # type: ignore[arg-type]
            )
        except Exception as e:
            logger.error("heartbeat: agent error: %s", e)
            return

        response = sink.collected

        # 5. Deliver or drop
        if self._is_heartbeat_ok(response):
            logger.debug("heartbeat: ok")
            return

        # Alert — deliver to the last active channel
        from squidbot.core.models import OutboundMessage  # noqa: PLC0415

        channel = self._tracker.channel
        session = self._tracker.session
        try:
            await channel.send(OutboundMessage(session=session, text=response))
        except Exception as e:
            logger.error("heartbeat: delivery error: %s", e)

    async def run(self) -> None:
        """
        Start the heartbeat loop.

        Sleeps for interval_minutes between ticks. Runs until cancelled.
        All tick errors are caught internally — this method never raises.
        """
        if not self._config.enabled:
            logger.info("heartbeat: disabled")
            return

        interval_s = self._config.interval_minutes * 60
        logger.info("heartbeat: started (every %dm)", self._config.interval_minutes)

        while True:
            await asyncio.sleep(interval_s)
            try:
                await self._tick()
            except Exception as e:
                logger.error("heartbeat: unexpected error in tick: %s", e)
