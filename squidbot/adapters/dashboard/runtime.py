"""Runtime coordination models for dashboard adapter state.

This module provides lightweight dataclasses for dashboard API handlers to read
gateway state, log buffers, and local-write safety metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_urlsafe
from typing import TYPE_CHECKING

from squidbot.adapters.dashboard.logs import DashboardLogBuffer
from squidbot.core.models import GatewayState

if TYPE_CHECKING:
    from squidbot.core.agent import AgentLoop


def _new_local_nonce() -> str:
    """Generate a non-empty local nonce token."""
    return token_urlsafe(24)


@dataclass
class DashboardRuntime:
    """In-memory runtime dependencies shared by dashboard endpoints.

    Args:
        state: Live gateway state snapshot source.
        log_buffer: Bounded in-memory log buffer for log-tail APIs.
        config_path: Optional settings file path for config endpoints.
        local_nonce: Runtime nonce required for mutating local requests.
        restart_requested_at: Timestamp of explicit restart intent.
        agent_loop: Optional agent loop used for streamed operator chat.
    """

    state: GatewayState
    log_buffer: DashboardLogBuffer
    config_path: Path | None
    local_nonce: str = field(default_factory=_new_local_nonce)
    restart_requested_at: datetime | None = None
    agent_loop: AgentLoop | None = None

    def mark_restart_requested(self) -> None:
        """Record the latest explicit restart intent timestamp.

        Returns:
            None.
        """
        self.restart_requested_at = datetime.now(UTC)
