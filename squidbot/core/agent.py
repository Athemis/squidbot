"""
Core agent loop for squidbot.

The agent loop coordinates the LLM, tool execution, memory, and channel delivery.
It has no direct knowledge of filesystems or network protocols — all external
interactions happen through the injected port implementations.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

from loguru import logger

from squidbot.core.memory import MemoryManager
from squidbot.core.models import (
    Message,
    OutboundMessage,
    Session,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from squidbot.core.ports import ChannelPort, LLMPort, ToolPort
from squidbot.core.registry import ToolRegistry
from squidbot.core.slash_commands import handle_slash_command

# Maximum number of tool-call rounds per user message.
# Prevents infinite loops in case of buggy tool chains.
MAX_TOOL_ROUNDS = 20
MAX_TRACKED_SESSION_GENERATIONS = 10_000
MAX_LOG_TOKEN_LEN = 128
SLASH_ACCESS_DENIED_TEXT = "Access denied: slash commands are only available to the owner."
SLASH_STATUS_BUILD_ERROR_TEXT = "Error: unable to build session status right now."
SLASH_REMEMBER_USAGE_TEXT = "Usage: /remember <text>"
SLASH_REMEMBER_UNAVAILABLE_TEXT = "Error: /remember unavailable (memory_write tool not configured)."
SLASH_REMEMBER_INVALID_RESULT_TEXT = "Error: memory_write returned an invalid result."
SLASH_ERROR_PREFIX = "Error: "


def _sanitize_log_value(value: str) -> str:
    """Return a single-token value safe for key=value log lines."""
    sanitized_chars = [
        char
        if char.isascii() and char.isprintable() and not char.isspace() and char != "="
        else "_"
        for char in value
    ]
    return "".join(sanitized_chars)[:MAX_LOG_TOKEN_LEN]


def _format_llm_error(exc: Exception) -> str:
    """Convert an LLM API exception into a user-readable error message."""
    name = type(exc).__name__
    msg = str(exc)
    # Extract just the human-readable part from openai error dicts
    if "AuthenticationError" in name:
        return "Error: invalid API key. Run 'squidbot onboard' to reconfigure."
    if "RateLimitError" in name:
        return "Error: rate limit reached. Try again in a moment."
    if "APIConnectionError" in name or "APITimeoutError" in name:
        return (
            "Error: could not reach the API. Check your internet connection and api_base setting."
        )
    # Generic fallback — show type and first line of message
    first_line = msg.splitlines()[0] if msg else name
    return f"Error ({name}): {first_line}"


class AgentLoop:
    """
    The core agent loop.

    For each user message, the loop:
    1. Builds the full message context (system prompt + history + user message)
    2. Calls the LLM and streams or collects the response
    3. If the LLM returns tool calls, executes them and loops back
    4. If the LLM returns text, delivers it to the channel and persists the exchange

    Memory failures (building history context or persisting the exchange) are treated
    as degraded mode: the agent still replies, but skips memory enrichment/persistence.

    Streaming behaviour is determined by channel.streaming:
    - True (e.g. CLI): each text chunk is sent immediately via channel.send()
    - False (e.g. Matrix, Email): chunks are accumulated, sent once at the end
    """

    def __init__(
        self,
        llm: LLMPort,
        memory: MemoryManager,
        registry: ToolRegistry,
        system_prompt: str,
    ) -> None:
        """
        Args:
            llm: The language model adapter.
            memory: The memory manager for history and memory.md.
            registry: The tool registry with all available tools.
            system_prompt: The base system prompt (AGENTS.md content).
        """
        self._llm = llm
        self._memory = memory
        self._registry = registry
        self._system_prompt = system_prompt
        self._session_generation: OrderedDict[str, int] = OrderedDict()
        self._session_backfill_next_turn: dict[str, bool] = {}
        self._max_tracked_session_generations = MAX_TRACKED_SESSION_GENERATIONS
        self._remember_lock = asyncio.Lock()

    def _get_session_generation(self, session_id: str) -> int:
        """Return session generation while refreshing recency order."""
        generation = self._session_generation.get(session_id)
        if generation is None:
            return 0
        self._session_generation.move_to_end(session_id)
        return generation

    def _set_session_generation(self, session_id: str, generation: int) -> None:
        """Persist session generation and evict oldest entries when over capacity."""
        self._session_generation[session_id] = generation
        self._session_generation.move_to_end(session_id)
        while len(self._session_generation) > self._max_tracked_session_generations:
            self._session_generation.popitem(last=False)

    def _effective_session_id(self, session: Session) -> str:
        """Return the logical session ID used for prompt history and persistence."""
        generation = self._get_session_generation(session.id)
        if generation == 0:
            return session.id
        return f"{session.id}#g{generation}"

    def _consume_backfill_flag(self, session: Session) -> bool:
        """Return whether to backfill history for this turn, consuming one-shot overrides."""
        return self._session_backfill_next_turn.pop(session.id, True)

    def _build_tool_definitions(
        self, extra_tools: Sequence[ToolPort] | None
    ) -> tuple[list[ToolDefinition], dict[str, ToolPort]]:
        extra_tool_map = {tool.name: tool for tool in (extra_tools or [])}
        tool_definitions = self._registry.get_definitions() + [
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
            )
            for tool in extra_tool_map.values()
        ]
        return tool_definitions, extra_tool_map

    async def _build_status_text(self, session: Session) -> str:
        """Return the deterministic slash status payload."""
        logical_session = self._effective_session_id(session)
        next_turn_backfill = self._session_backfill_next_turn.get(session.id, True)
        backfill_text = "true" if next_turn_backfill else "false"
        history_count = await self._memory.count_session_history(
            session=session,
            session_id=logical_session,
        )
        return (
            "Current session status:\n"
            f"- channel: {session.channel}\n"
            f"- physical_session: {session.id}\n"
            f"- logical_session: {logical_session}\n"
            f"- next_turn_history_backfill: {backfill_text}\n"
            f"- history_messages: {history_count}"
        )

    def _resolve_slash_actor_sender(
        self,
        session: Session,
        user_sender_id: str | None,
        outbound_metadata: dict[str, Any] | None,
    ) -> str | None:
        """Return sender identity used for slash authorization checks."""
        if session.channel == "matrix":
            sender = (outbound_metadata or {}).get("matrix_sender_id")
            if isinstance(sender, str) and sender:
                return sender
            return None
        if user_sender_id is not None:
            return user_sender_id
        return session.sender_id

    @staticmethod
    def _append_memory_note(existing: str, note: str) -> str:
        """Append a single markdown bullet line to memory content."""
        note_line = f"- {note.strip()}"
        if not existing.strip():
            return note_line
        return f"{existing.rstrip()}\n{note_line}"

    async def _run_slash_remember(
        self,
        note: str,
        extra_tools: Sequence[ToolPort] | None,
    ) -> str:
        """Execute /remember by merging and writing global memory."""
        extra_tool_map = {tool.name: tool for tool in (extra_tools or [])}
        memory_tool = extra_tool_map.get("memory_write") or self._registry.get("memory_write")
        if memory_tool is None:
            return SLASH_REMEMBER_UNAVAILABLE_TEXT

        try:
            async with self._remember_lock:
                existing = await self._memory.load_global_memory_text()
                merged = self._append_memory_note(existing, note)
                result = await memory_tool.execute(content=merged)
                if not isinstance(result, ToolResult):
                    return SLASH_REMEMBER_INVALID_RESULT_TEXT
                return result.content
        except Exception as exc:  # noqa: BLE001
            return f"{SLASH_ERROR_PREFIX}{exc}"

    async def _run_llm_stream(
        self,
        llm: LLMPort,
        messages: list[Message],
        tool_definitions: list[ToolDefinition],
        channel: ChannelPort,
        session: Session,
        outbound_metadata: dict[str, Any] | None,
    ) -> tuple[str, list[ToolCall], str | None]:
        tool_calls: list[ToolCall] = []
        text_chunks: list[str] = []
        reasoning_content: str | None = None

        response_stream = await llm.chat(messages, tool_definitions)
        async for chunk in response_stream:
            if isinstance(chunk, str):
                text_chunks.append(chunk)
                if channel.streaming:
                    await channel.send(
                        OutboundMessage(
                            session=session,
                            text=chunk,
                            metadata=outbound_metadata or {},
                        )
                    )
                continue

            if isinstance(chunk, list):
                tool_calls = chunk
                continue

            if isinstance(chunk, tuple):
                tool_calls, reasoning_content = chunk

        return "".join(text_chunks), tool_calls, reasoning_content

    def _is_concurrent(self, tool_call: ToolCall, extra_tools: dict[str, ToolPort]) -> bool:
        """Return True if the tool for this call declares concurrent-safe execution.

        Defaults to True when the tool does not declare a ``concurrent`` attribute.
        LLM-batched tool calls are assumed to be independent; set ``concurrent = False``
        on tools that must not run alongside other tools in the same batch.
        """
        tool = extra_tools.get(tool_call.name) or self._registry.get(tool_call.name)
        return bool(getattr(tool, "concurrent", True))

    async def _append_tool_results(
        self,
        messages: list[Message],
        tool_calls: list[ToolCall],
        extra_tools: dict[str, ToolPort],
        *,
        session_id: str,
        round_number: int,
    ) -> None:
        """Execute tool calls and append results to messages.

        When every tool in the batch has ``concurrent = True`` (the default),
        all calls are executed in parallel via asyncio.gather.
        Per-call exceptions are converted to tool error messages.

        When any tool declares ``concurrent = False`` the entire batch is executed
        sequentially in call order to avoid unintended side-effect interleaving.

        Args:
            messages: Message list to append tool result messages to.
            tool_calls: Tool calls from the LLM to execute.
            extra_tools: Per-run extra tools keyed by name.
            session_id: Session identifier used for lifecycle logs.
            round_number: 1-based tool-call round number used for lifecycle logs.
        """
        safe_session_id = _sanitize_log_value(session_id)

        async def _execute_one(tool_call: ToolCall) -> tuple[Message, bool]:
            call_started = time.monotonic()
            safe_tool_name = _sanitize_log_value(tool_call.name)
            safe_call_id = _sanitize_log_value(tool_call.id)
            try:
                extra_tool = extra_tools.get(tool_call.name)
                if extra_tool is not None:
                    raw = await extra_tool.execute(**tool_call.arguments)
                    result = ToolResult(
                        tool_call_id=tool_call.id,
                        content=raw.content,
                        is_error=raw.is_error,
                    )
                else:
                    result = await self._registry.execute(
                        tool_call.name,
                        tool_call_id=tool_call.id,
                        **tool_call.arguments,
                    )
            except Exception as exc:  # noqa: BLE001
                duration_ms = int((time.monotonic() - call_started) * 1000)
                logger.info(
                    "agent.tool.call.done session_id={} round={} tool={} "
                    "call_id={} duration_ms={} status=error",
                    safe_session_id,
                    round_number,
                    safe_tool_name,
                    safe_call_id,
                    duration_ms,
                )
                return (
                    Message(
                        role="tool",
                        content=f"Error: {exc}",
                        tool_call_id=tool_call.id,
                    ),
                    True,
                )

            duration_ms = int((time.monotonic() - call_started) * 1000)
            status = "error" if result.is_error else "ok"
            logger.info(
                "agent.tool.call.done session_id={} round={} tool={} "
                "call_id={} duration_ms={} status={}",
                safe_session_id,
                round_number,
                safe_tool_name,
                safe_call_id,
                duration_ms,
                status,
            )
            return (
                Message(
                    role="tool",
                    content=result.content,
                    tool_call_id=tool_call.id,
                ),
                result.is_error,
            )

        run_parallel = all(self._is_concurrent(tc, extra_tools) for tc in tool_calls)
        logger.info(
            "agent.tool.round.start session_id={} round={} count={} parallel={}",
            safe_session_id,
            round_number,
            len(tool_calls),
            run_parallel,
        )
        round_started = time.monotonic()

        results: list[tuple[Message, bool]]
        if run_parallel:
            results = list(await asyncio.gather(*[_execute_one(tc) for tc in tool_calls]))
        else:
            results = []
            for tc in tool_calls:
                results.append(await _execute_one(tc))

        ok_count = sum(1 for _, is_error in results if not is_error)
        error_count = len(results) - ok_count
        round_duration_ms = int((time.monotonic() - round_started) * 1000)
        logger.info(
            "agent.tool.round.done session_id={} round={} duration_ms={} "
            "ok_count={} error_count={}",
            safe_session_id,
            round_number,
            round_duration_ms,
            ok_count,
            error_count,
        )

        for message, _ in results:
            messages.append(message)

    async def _deliver_final_text(
        self,
        channel: ChannelPort,
        session: Session,
        final_text: str,
        outbound_metadata: dict[str, Any] | None,
    ) -> None:
        if not channel.streaming and final_text:
            await channel.send(
                OutboundMessage(
                    session=session,
                    text=final_text,
                    metadata=outbound_metadata or {},
                )
            )

    async def run(
        self,
        session: Session,
        user_message: str | list[dict[str, Any]],
        channel: ChannelPort,
        *,
        llm: LLMPort | None = None,
        extra_tools: Sequence[ToolPort] | None = None,
        outbound_metadata: dict[str, Any] | None = None,
        user_sender_id: str | None = None,
    ) -> None:
        """
        Process a single user message and deliver the reply to the channel.

        This method is intentionally resilient at the memory boundary:
        - If building the full message context fails, it falls back to system+user only.
        - If persisting the exchange fails, the user-visible reply is still delivered.

        When user_message is a multimodal list, the text portion is extracted as a
        fallback for memory context and persistence. The full multimodal payload is
        substituted into the last user message before the LLM call.

        Args:
            session: The conversation session (carries channel + sender identity).
            user_message: The user's input — either plain text or an OpenAI multimodal
                          content list (with text and image_url blocks).
            channel: The channel to deliver the response to.
            llm: Optional LLM override for this single run. If provided,
                 replaces self._llm for the duration of this call only.
            extra_tools: Optional list of additional tools available for this run only.
                         These are merged with the registry for this call and do not
                         mutate self._registry.
            outbound_metadata: Optional channel-routing metadata to attach to outbound
                               messages emitted during this run.
            user_sender_id: Optional sender attribution used for persistence.
                Defaults to session.sender_id.
        """
        selected_llm = llm if llm is not None else self._llm

        # Derive a plain-text fallback for memory operations when input is multimodal.
        if isinstance(user_message, list):
            text_blocks = [
                block["text"]
                for block in user_message
                if block.get("type") == "text" and isinstance(block.get("text"), str)
            ]
            text_fallback: str = " ".join(text_blocks) if text_blocks else "[multimodal message]"
        else:
            text_fallback = user_message

        if isinstance(user_message, str):
            slash_result = handle_slash_command(user_message)
            if slash_result.handled:
                actor_sender = self._resolve_slash_actor_sender(
                    session,
                    user_sender_id,
                    outbound_metadata,
                )
                if not self._memory.is_owner_sender(actor_sender, session.channel):
                    await channel.send(
                        OutboundMessage(
                            session=session,
                            text=SLASH_ACCESS_DENIED_TEXT,
                            metadata=outbound_metadata or {},
                        )
                    )
                    return

                if slash_result.reset_requested:
                    next_generation = self._get_session_generation(session.id) + 1
                    self._set_session_generation(session.id, next_generation)
                    # /new starts a fresh logical session without automatic history backfill.
                    self._session_backfill_next_turn[session.id] = False

                slash_text = slash_result.response_text
                if slash_result.action == "status":
                    try:
                        slash_text = await self._build_status_text(session)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "agent.run: /status failed while building status for session={}: {}",
                            session.id,
                            exc,
                        )
                        slash_text = SLASH_STATUS_BUILD_ERROR_TEXT
                if slash_result.action == "remember":
                    remember_note = slash_result.argument or ""
                    if not remember_note:
                        slash_text = SLASH_REMEMBER_USAGE_TEXT
                    else:
                        slash_text = await self._run_slash_remember(remember_note, extra_tools)

                await channel.send(
                    OutboundMessage(
                        session=session,
                        text=slash_text,
                        metadata=outbound_metadata or {},
                    )
                )
                return

        await channel.send_typing(session.id)

        effective_session_id = self._effective_session_id(session)
        load_history = self._consume_backfill_flag(session)

        try:
            messages = await self._memory.build_messages(
                user_message=text_fallback,
                system_prompt=self._system_prompt,
                session=session,
                session_id=effective_session_id,
                load_history=load_history,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent.run: build_messages failed, fallback to minimal context: {}", exc)
            messages = [
                Message(role="system", content=self._system_prompt),
                Message(role="user", content=text_fallback),
            ]

        # Replace the last user message content with the full multimodal payload when present.
        # If no user slot exists (e.g. empty history), append one so the LLM always
        # receives the full multimodal payload.
        if isinstance(user_message, list):
            replaced_user = False
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].role == "user":
                    messages[i] = Message(
                        role="user",
                        content=user_message,
                        channel=messages[i].channel,
                        sender_id=messages[i].sender_id,
                    )
                    replaced_user = True
                    break
            if not replaced_user:
                messages.append(
                    Message(
                        role="user",
                        content=user_message,
                        channel=session.channel,
                        sender_id=session.sender_id,
                    )
                )

        tool_definitions, extra_tool_map = self._build_tool_definitions(extra_tools)

        final_text = ""
        tool_round = 0

        while tool_round < MAX_TOOL_ROUNDS:
            try:
                text_response, tool_calls, reasoning_content = await self._run_llm_stream(
                    llm=selected_llm,
                    messages=messages,
                    tool_definitions=tool_definitions,
                    channel=channel,
                    session=session,
                    outbound_metadata=outbound_metadata,
                )
            except Exception as e:
                error_msg = _format_llm_error(e)
                await channel.send(
                    OutboundMessage(
                        session=session,
                        text=error_msg,
                        metadata=outbound_metadata or {},
                    )
                )
                logger.error("agent.run: llm failed for session={}: {}", session.id, e)
                return

            if text_response:
                final_text = text_response

            if not tool_calls:
                # No tool calls — the agent is done
                break

            messages.append(
                Message(
                    role="assistant",
                    content=text_response,
                    tool_calls=tool_calls,
                    reasoning_content=reasoning_content,
                )
            )

            tool_round += 1

            await self._append_tool_results(
                messages,
                tool_calls,
                extra_tool_map,
                session_id=session.id,
                round_number=tool_round,
            )
        else:
            final_text = final_text or "Error: maximum tool call rounds exceeded."

        await channel.send_typing(session.id, typing=False)
        await self._deliver_final_text(channel, session, final_text, outbound_metadata)

        # Persist the exchange — use text_fallback to avoid storing base64 payloads.
        try:
            await self._memory.persist_exchange(
                channel=session.channel,
                sender_id=user_sender_id or session.sender_id,
                user_message=text_fallback,
                assistant_reply=final_text,
                session_id=effective_session_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent.run: persist_exchange failed for session={}: {}", session.id, exc)
            return
