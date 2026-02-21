"""
Core agent loop for squidbot.

The agent loop coordinates the LLM, tool execution, memory, and channel delivery.
It has no direct knowledge of filesystems or network protocols — all external
interactions happen through the injected port implementations.
"""

from __future__ import annotations

from squidbot.core.memory import MemoryManager
from squidbot.core.models import Message, OutboundMessage, Session, ToolCall
from squidbot.core.ports import ChannelPort, LLMPort
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

    async def run(self, session: Session, user_message: str, channel: ChannelPort) -> None:
        """
        Process a single user message and deliver the reply to the channel.

        Args:
            session: The conversation session (carries channel + sender identity).
            user_message: The user's input text.
            channel: The channel to deliver the response to.
        """
        messages = await self._memory.build_messages(
            session_id=session.id,
            system_prompt=self._system_prompt,
            user_message=user_message,
        )
        tool_definitions = self._registry.get_definitions()

        final_text = ""
        tool_round = 0

        while tool_round < MAX_TOOL_ROUNDS:
            tool_calls: list[ToolCall] = []
            text_chunks: list[str] = []

            try:
                response_stream = await self._llm.chat(messages, tool_definitions)
                async for chunk in response_stream:
                    if isinstance(chunk, str):
                        text_chunks.append(chunk)
                        if channel.streaming:
                            # Forward each chunk immediately for typewriter effect
                            await channel.send(OutboundMessage(session=session, text=chunk))
                    elif isinstance(chunk, list):
                        tool_calls = chunk
            except Exception as e:
                error_msg = _format_llm_error(e)
                await channel.send(OutboundMessage(session=session, text=error_msg))
                return

            text_response = "".join(text_chunks)
            if text_response:
                final_text = text_response

            if not tool_calls:
                # No tool calls — the agent is done
                break

            # Execute tool calls and append results to message history
            messages.append(
                Message(
                    role="assistant",
                    content=text_response,
                    tool_calls=tool_calls,
                )
            )

            for tc in tool_calls:
                result = await self._registry.execute(tc.name, tool_call_id=tc.id, **tc.arguments)
                messages.append(
                    Message(
                        role="tool",
                        content=result.content,
                        tool_call_id=tc.id,
                    )
                )

            tool_round += 1
        else:
            final_text = final_text or "Error: maximum tool call rounds exceeded."

        # For non-streaming channels, send the full accumulated reply at the end
        if not channel.streaming and final_text:
            await channel.send(OutboundMessage(session=session, text=final_text))

        # Persist the exchange
        await self._memory.persist_exchange(
            session_id=session.id,
            user_message=user_message,
            assistant_reply=final_text,
        )
