"""
Core agent loop for squidbot.

The agent loop coordinates the LLM, tool execution, memory, and channel delivery.
It has no direct knowledge of filesystems or network protocols — all external
interactions happen through the injected port implementations.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

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

# Maximum number of tool-call rounds per user message.
# Prevents infinite loops in case of buggy tool chains.
MAX_TOOL_ROUNDS = 20


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
                            metadata=dict(outbound_metadata or {}),
                        )
                    )
                continue

            if isinstance(chunk, list):
                tool_calls = chunk
                continue

            if isinstance(chunk, tuple):
                tool_calls, reasoning_content = chunk

        return "".join(text_chunks), tool_calls, reasoning_content

    async def _append_tool_results(
        self,
        messages: list[Message],
        tool_calls: list[ToolCall],
        extra_tools: dict[str, ToolPort],
    ) -> None:
        for tool_call in tool_calls:
            extra_tool = extra_tools.get(tool_call.name)
            if extra_tool is not None:
                extra_result = await extra_tool.execute(**tool_call.arguments)
                result = ToolResult(
                    tool_call_id=tool_call.id,
                    content=extra_result.content,
                    is_error=extra_result.is_error,
                )
            else:
                result = await self._registry.execute(
                    tool_call.name,
                    tool_call_id=tool_call.id,
                    **tool_call.arguments,
                )

            messages.append(
                Message(
                    role="tool",
                    content=result.content,
                    tool_call_id=tool_call.id,
                )
            )

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
                    metadata=dict(outbound_metadata or {}),
                )
            )

    async def run(
        self,
        session: Session,
        user_message: str,
        channel: ChannelPort,
        *,
        llm: LLMPort | None = None,
        extra_tools: Sequence[ToolPort] | None = None,
        outbound_metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Process a single user message and deliver the reply to the channel.

        This method is intentionally resilient at the memory boundary:
        - If building the full message context fails, it falls back to system+user only.
        - If persisting the exchange fails, the user-visible reply is still delivered.

        Args:
            session: The conversation session (carries channel + sender identity).
            user_message: The user's input text.
            channel: The channel to deliver the response to.
            llm: Optional LLM override for this single run. If provided,
                 replaces self._llm for the duration of this call only.
            extra_tools: Optional list of additional tools available for this run only.
                         These are merged with the registry for this call and do not
                         mutate self._registry.
            outbound_metadata: Optional channel-routing metadata to attach to outbound
                               messages emitted during this run.
        """
        selected_llm = llm if llm is not None else self._llm

        try:
            messages = await self._memory.build_messages(
                user_message=user_message,
                system_prompt=self._system_prompt,
            )
        except Exception:
            messages = [
                Message(role="system", content=self._system_prompt),
                Message(role="user", content=user_message),
            ]
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
                        metadata=dict(outbound_metadata or {}),
                    )
                )
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

            await self._append_tool_results(messages, tool_calls, extra_tool_map)

            tool_round += 1
        else:
            final_text = final_text or "Error: maximum tool call rounds exceeded."

        await self._deliver_final_text(channel, session, final_text, outbound_metadata)

        # Persist the exchange
        try:
            await self._memory.persist_exchange(
                channel=session.channel,
                sender_id=session.sender_id,
                user_message=user_message,
                assistant_reply=final_text,
            )
        except Exception:
            return
