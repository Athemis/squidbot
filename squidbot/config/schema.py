"""
Configuration schema for squidbot.

Settings are loaded from a JSON file (default: ~/.squidbot/config.json).
Individual fields can be overridden via environment variables using the
SQUIDBOT_ prefix (e.g., SQUIDBOT_LLM__API_KEY).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path.home() / ".squidbot" / "config.json"


class LLMConfig(BaseModel):
    """Configuration for the language model endpoint."""

    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "anthropic/claude-opus-4-5"
    max_tokens: int = 8192
    max_context_tokens: int = 100_000


class HeartbeatConfig(BaseModel):
    """Configuration for the periodic heartbeat service."""

    enabled: bool = True
    interval_minutes: int = 30
    prompt: str = (
        "Read HEARTBEAT.md if it exists in your workspace. "
        "Follow any instructions strictly. Do not repeat tasks from prior turns. "
        "If nothing needs attention, reply with just: HEARTBEAT_OK"
    )
    active_hours_start: str = "00:00"  # HH:MM inclusive
    active_hours_end: str = "24:00"  # HH:MM exclusive; 24:00 = end of day
    timezone: str = "local"  # IANA tz name or "local" (host timezone)


class AgentConfig(BaseModel):
    """Configuration for agent behavior."""

    workspace: str = str(Path.home() / ".squidbot" / "workspace")
    system_prompt_file: str = "AGENTS.md"
    restrict_to_workspace: bool = True
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


class ShellToolConfig(BaseModel):
    enabled: bool = True


class WebSearchConfig(BaseModel):
    enabled: bool = False
    provider: str = "searxng"  # "searxng", "brave", "duckduckgo"
    url: str = ""
    api_key: str = ""


class McpServerConfig(BaseModel):
    """Configuration for a single MCP server connection."""

    transport: Literal["stdio", "http"] = "stdio"
    # stdio transport
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    # http transport
    url: str = ""


class ToolsConfig(BaseModel):
    shell: ShellToolConfig = Field(default_factory=ShellToolConfig)
    files: ShellToolConfig = Field(default_factory=ShellToolConfig)  # reuse enabled flag
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)


class MatrixChannelConfig(BaseModel):
    """Configuration for the Matrix channel adapter."""

    enabled: bool = False
    homeserver: str = "https://matrix.org"
    user_id: str = ""
    access_token: str = ""
    device_id: str = "SQUIDBOT01"
    room_ids: list[str] = Field(default_factory=list)
    group_policy: str = "mention"  # "open", "mention", "allowlist"
    allowlist: list[str] = Field(default_factory=list)


class EmailChannelConfig(BaseModel):
    enabled: bool = False
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    from_address: str = ""
    allow_from: list[str] = Field(default_factory=list)
    tls_verify: bool = True
    use_tls: bool = True  # STARTTLS for SMTP


class ChannelsConfig(BaseModel):
    matrix: MatrixChannelConfig = Field(default_factory=MatrixChannelConfig)
    email: EmailChannelConfig = Field(default_factory=EmailChannelConfig)


# Alias for backwards-compatible imports
ChannelConfig = ChannelsConfig


class SkillsConfig(BaseModel):
    """Configuration for the skills system."""

    extra_dirs: list[str] = Field(
        default_factory=list,
        description="Additional directories to search for skills, in priority order.",
    )


class Settings(BaseModel):
    """Root configuration object for squidbot."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    agents: AgentConfig = Field(default_factory=AgentConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> Settings:
        """
        Load settings from a JSON file.

        Missing keys use their default values.
        The file is optional — if it doesn't exist, all defaults apply.
        """
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def save(self, path: Path = DEFAULT_CONFIG_PATH) -> None:
        """Persist settings to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self.model_dump_json(indent=2, exclude_none=False),
            encoding="utf-8",
        )
