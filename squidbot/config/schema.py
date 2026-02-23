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

from pydantic import BaseModel, Field, model_validator

DEFAULT_CONFIG_PATH = Path.home() / ".squidbot" / "config.json"


class LLMProviderConfig(BaseModel):
    """API endpoint credentials for an LLM provider."""

    api_base: str
    api_key: str = ""


class LLMModelConfig(BaseModel):
    """A named model definition referencing a provider."""

    provider: str
    model: str
    max_tokens: int = 8192
    max_context_tokens: int = 100_000


class LLMPoolEntry(BaseModel):
    """One entry in a pool's fallback list — references a named model."""

    model: str


class LLMConfig(BaseModel):
    """Root LLM configuration using the provider/model/pool hierarchy."""

    default_pool: str = "default"
    providers: dict[str, LLMProviderConfig] = Field(default_factory=dict)
    models: dict[str, LLMModelConfig] = Field(default_factory=dict)
    pools: dict[str, list[LLMPoolEntry]] = Field(default_factory=dict)


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
    pool: str = ""  # empty = use llm.default_pool


class AgentConfig(BaseModel):
    """Configuration for agent behavior."""

    workspace: str = str(Path.home() / ".squidbot" / "workspace")
    restrict_to_workspace: bool = True
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    # TODO: replace with token-based threshold derived from the model's context window size
    consolidation_threshold: int = 100
    keep_recent_ratio: float = 0.2

    @model_validator(mode="after")
    def _validate_consolidation(self) -> AgentConfig:
        """Validate consolidation config values are consistent and in range."""
        if self.consolidation_threshold <= 0:
            raise ValueError("agents.consolidation_threshold must be > 0")
        if not (0 < self.keep_recent_ratio < 1):
            raise ValueError("agents.keep_recent_ratio must be between 0 and 1 (exclusive)")
        return self


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


class SpawnProfile(BaseModel):
    """Configuration for a named sub-agent profile."""

    system_prompt: str = ""
    system_prompt_file: str = ""  # filename relative to workspace
    bootstrap_files: list[str] = Field(default_factory=list)  # [] = default allowlist
    tools: list[str] = Field(default_factory=list)
    pool: str = ""  # empty = use llm.default_pool


class SpawnSettings(BaseModel):
    """Configuration for the spawn tool."""

    enabled: bool = False
    profiles: dict[str, SpawnProfile] = Field(default_factory=dict)


class SearchHistoryConfig(BaseModel):
    """Configuration for the search_history tool."""

    enabled: bool = True


class ToolsConfig(BaseModel):
    shell: ShellToolConfig = Field(default_factory=ShellToolConfig)
    files: ShellToolConfig = Field(default_factory=ShellToolConfig)  # reuse enabled flag
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    search_history: SearchHistoryConfig = Field(default_factory=SearchHistoryConfig)
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    spawn: SpawnSettings = Field(default_factory=SpawnSettings)


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
    """Configuration for the Email channel adapter."""

    enabled: bool = False
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    from_address: str = ""
    allow_from: list[str] = Field(default_factory=list)
    poll_interval_seconds: int = 60
    tls: bool = True  # False = plaintext (local test servers only)
    tls_verify: bool = True  # False = skip certificate verification
    imap_starttls: bool = False  # True = STARTTLS on port 143 instead of SSL on 993
    smtp_starttls: bool = True  # True = STARTTLS on port 587 (default); False = SSL on 465


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

    @model_validator(mode="after")
    def _validate_llm_references(self) -> Settings:
        """
        Validate all pool/model/provider cross-references at config load time.

        Raises:
            ValueError: If any referenced pool, model, or provider is missing,
                        or if any pool-aware component references an unknown pool.
        """
        llm = self.llm
        # Only validate if any pools are configured
        if not llm.pools:
            return self

        # default_pool must exist in pools
        if llm.default_pool and llm.default_pool not in llm.pools:
            raise ValueError(f"llm.default_pool '{llm.default_pool}' not found in llm.pools")

        # Every pool entry's model must exist in llm.models
        for pool_name, entries in llm.pools.items():
            for entry in entries:
                if entry.model not in llm.models:
                    raise ValueError(f"Pool '{pool_name}' references unknown model '{entry.model}'")

        # Every model's provider must exist in llm.providers
        for model_name, model_cfg in llm.models.items():
            if model_cfg.provider not in llm.providers:
                raise ValueError(
                    f"Model '{model_name}' references unknown provider '{model_cfg.provider}'"
                )

        # heartbeat.pool must exist (if set)
        hb_pool = self.agents.heartbeat.pool
        if hb_pool and hb_pool not in llm.pools:
            raise ValueError(f"agents.heartbeat.pool '{hb_pool}' not found in llm.pools")

        # spawn profile pools must exist (if set)
        for prof_name, prof in self.tools.spawn.profiles.items():
            if prof.pool and prof.pool not in llm.pools:
                raise ValueError(
                    f"tools.spawn.profiles.{prof_name}.pool '{prof.pool}' not found in llm.pools"
                )

        return self

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
