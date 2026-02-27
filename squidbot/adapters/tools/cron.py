"""Cron management tools for the agent runtime."""

from __future__ import annotations

from typing import Any

from squidbot.core import cron_ops
from squidbot.core.models import CronJob, ToolResult
from squidbot.core.ports import MemoryPort, ToolPort


class CronListTool:
    """List all configured cron jobs."""

    name = "cron_list"
    description = "List all configured cron jobs."
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, storage: MemoryPort) -> None:
        self._storage = storage

    async def execute(self, **kwargs: Any) -> ToolResult:
        jobs = await self._storage.load_cron_jobs()
        return ToolResult(tool_call_id="", content=cron_ops.format_jobs(jobs))


class CronAddTool:
    """Create a cron job with channel-aware defaults."""

    name = "cron_add"
    description = "Create a cron job with schedule, target channel, and message."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Human-readable cron job name."},
            "message": {
                "type": "string",
                "description": "Message text to send when the job fires.",
            },
            "schedule": {
                "type": "string",
                "description": (
                    "Cron expression (e.g. '0 9 * * *') or interval form ('every 3600')."
                ),
            },
            "timezone": {
                "type": "string",
                "description": "Timezone for cron expression schedules.",
            },
            "channel": {
                "type": "string",
                "description": "Target session ID for delivery, e.g. 'matrix:@user:matrix.org'.",
            },
            "enabled": {"type": "boolean", "description": "Whether the job is enabled."},
        },
        "required": ["name", "message", "schedule"],
    }

    def __init__(
        self,
        storage: MemoryPort,
        default_channel: str,
        default_metadata: dict[str, Any],
    ) -> None:
        self._storage = storage
        self._default_channel = default_channel
        self._default_metadata = dict(default_metadata)

    async def execute(self, **kwargs: Any) -> ToolResult:
        name_raw = kwargs.get("name")
        message_raw = kwargs.get("message")
        schedule_raw = kwargs.get("schedule")
        if not isinstance(name_raw, str) or not name_raw:
            return ToolResult(tool_call_id="", content="Error: name is required", is_error=True)
        if not isinstance(message_raw, str) or not message_raw:
            return ToolResult(tool_call_id="", content="Error: message is required", is_error=True)
        if not isinstance(schedule_raw, str) or not schedule_raw:
            return ToolResult(tool_call_id="", content="Error: schedule is required", is_error=True)

        timezone_raw = kwargs.get("timezone")
        timezone = timezone_raw if isinstance(timezone_raw, str) and timezone_raw else "local"

        channel_raw_obj = kwargs.get("channel")
        target_channel: str
        if isinstance(channel_raw_obj, str) and channel_raw_obj:
            has_explicit_channel = True
            target_channel = channel_raw_obj
        else:
            has_explicit_channel = False
            target_channel = self._default_channel

        if not has_explicit_channel and self._default_channel.startswith("cli:"):
            return ToolResult(
                tool_call_id="",
                content="Error: channel is required when scheduling from CLI sessions",
                is_error=True,
            )

        enabled_raw = kwargs.get("enabled", True)
        if not isinstance(enabled_raw, bool):
            return ToolResult(
                tool_call_id="", content="Error: enabled must be a boolean", is_error=True
            )

        metadata, metadata_error = _build_cron_metadata(
            target_channel=target_channel,
            default_metadata=self._default_metadata,
            job_name=name_raw,
        )
        if metadata_error is not None:
            return ToolResult(tool_call_id="", content=f"Error: {metadata_error}", is_error=True)

        job = CronJob(
            id=cron_ops.generate_job_id(),
            name=name_raw,
            message=message_raw,
            schedule=schedule_raw,
            channel=target_channel,
            enabled=enabled_raw,
            timezone=timezone,
            metadata=metadata,
        )
        jobs = await self._storage.load_cron_jobs()
        try:
            updated = cron_ops.add_job(jobs, job)
        except ValueError as exc:
            return ToolResult(tool_call_id="", content=f"Error: {exc}", is_error=True)
        await self._storage.save_cron_jobs(updated)
        return ToolResult(tool_call_id="", content=f"OK: created cron job id={job.id}")


class CronRemoveTool:
    """Remove a cron job by ID."""

    name = "cron_remove"
    description = "Remove a cron job by its ID."
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Cron job ID to remove."},
        },
        "required": ["job_id"],
    }

    def __init__(self, storage: MemoryPort) -> None:
        self._storage = storage

    async def execute(self, **kwargs: Any) -> ToolResult:
        job_id_raw = kwargs.get("job_id")
        if not isinstance(job_id_raw, str) or not job_id_raw:
            return ToolResult(tool_call_id="", content="Error: job_id is required", is_error=True)
        jobs = await self._storage.load_cron_jobs()
        updated, removed = cron_ops.remove_job(jobs, job_id_raw)
        if not removed:
            return ToolResult(
                tool_call_id="", content=f"Error: job '{job_id_raw}' not found", is_error=True
            )
        await self._storage.save_cron_jobs(updated)
        return ToolResult(tool_call_id="", content=f"OK: removed cron job id={job_id_raw}")


class CronSetEnabledTool:
    """Enable or disable a cron job by ID."""

    name = "cron_set_enabled"
    description = "Enable or disable a cron job by its ID."
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Cron job ID to update."},
            "enabled": {"type": "boolean", "description": "New enabled state for the job."},
        },
        "required": ["job_id", "enabled"],
    }

    def __init__(self, storage: MemoryPort) -> None:
        self._storage = storage

    async def execute(self, **kwargs: Any) -> ToolResult:
        job_id_raw = kwargs.get("job_id")
        enabled_raw = kwargs.get("enabled")
        if not isinstance(job_id_raw, str) or not job_id_raw:
            return ToolResult(tool_call_id="", content="Error: job_id is required", is_error=True)
        if not isinstance(enabled_raw, bool):
            return ToolResult(tool_call_id="", content="Error: enabled is required", is_error=True)
        jobs = await self._storage.load_cron_jobs()
        updated, found = cron_ops.set_enabled(jobs, job_id_raw, enabled_raw)
        if not found:
            return ToolResult(
                tool_call_id="", content=f"Error: job '{job_id_raw}' not found", is_error=True
            )
        await self._storage.save_cron_jobs(updated)
        state = "enabled" if enabled_raw else "disabled"
        return ToolResult(tool_call_id="", content=f"OK: {state} cron job id={job_id_raw}")


def _build_cron_metadata(
    *,
    target_channel: str,
    default_metadata: dict[str, Any],
    job_name: str,
) -> tuple[dict[str, Any], str | None]:
    """Build channel-specific cron delivery metadata."""
    channel_prefix = target_channel.split(":", 1)[0]
    if channel_prefix == "matrix":
        room_id_raw = default_metadata.get("matrix_room_id")
        if not isinstance(room_id_raw, str) or not room_id_raw:
            return (
                {},
                "matrix_room_id is required to schedule Matrix cron jobs",
            )
        metadata: dict[str, Any] = {"matrix_room_id": room_id_raw}
        thread_root_raw = default_metadata.get("matrix_thread_root")
        if isinstance(thread_root_raw, str) and thread_root_raw:
            metadata["matrix_thread_root"] = thread_root_raw
        return metadata, None

    if channel_prefix == "email":
        metadata = {"email_subject": f"[squidbot] {job_name}"}
        return metadata, None

    return {}, None


def build_cron_tools(
    *,
    storage: MemoryPort,
    default_channel: str,
    default_metadata: dict[str, Any],
) -> list[ToolPort]:
    """Construct all cron tool instances for one inbound context."""
    return [
        CronListTool(storage=storage),
        CronAddTool(
            storage=storage,
            default_channel=default_channel,
            default_metadata=default_metadata,
        ),
        CronRemoveTool(storage=storage),
        CronSetEnabledTool(storage=storage),
    ]
