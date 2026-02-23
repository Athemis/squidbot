"""
Core memory manager for squidbot.

Coordinates short-term (in-session history), global long-term (MEMORY.md),
and per-session consolidation summaries. The manager is pure domain logic —
it takes a MemoryPort as dependency and contains no I/O or external service calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from squidbot.core.models import Message
from squidbot.core.ports import MemoryPort, SkillsPort

if TYPE_CHECKING:
    from squidbot.core.ports import LLMPort

# Injected into the system prompt one turn before consolidation fires.
# Prompts the agent to use memory_write to preserve anything critical.
_CONSOLIDATION_WARNING = (
    "\n\n[System: Conversation history will soon be summarized and condensed. "
    "Use the memory_write tool now to preserve anything critical before it happens.]\n"
)

_CONSOLIDATION_PROMPT = (
    "Summarize the following conversation history into a concise memory entry. "
    "Focus on key facts, decisions, and context useful for future conversations. "
    "Do not include small talk or filler.\n\n"
    "Conversation history:\n{history}\n\n"
    "Provide a summary of approximately {sentences} sentences suitable for "
    "appending to a memory document."
)

_CONSOLIDATION_SYSTEM = (
    "You are a memory consolidation assistant. "
    "Your sole task is to produce concise, factual summaries of conversation history. "
    "Output only the summary text — no preamble, no commentary, no formatting."
)

_META_CONSOLIDATION_SYSTEM = (
    "You are a memory consolidation assistant. "
    "You are given an existing session summary that has grown too long. "
    "Compress it into a shorter summary that retains all facts, decisions, and context. "
    "Output only the summary text — no preamble, no commentary, no formatting."
)

_META_CONSOLIDATION_PROMPT = (
    "The following is a session summary that has grown too long and needs to be compressed.\n\n"
    "{summary}\n\n"
    "Rewrite this as a compact summary of approximately {sentences} sentences. "
    "Retain all facts, decisions, and context. Do not discard any information."
)

_META_SUMMARY_WORD_LIMIT = 600
_META_SUMMARY_SENTENCES = 8


class MemoryManager:
    """
    Manages message history and memory documents for agent sessions.

    Responsibilities:
    - Build the full message list for each LLM call (system + history + user)
    - Inject memory.md content into the system prompt
    - Inject skills XML block and always-skill bodies into the system prompt
    - Warn the agent one turn before consolidation via _CONSOLIDATION_WARNING
    - Consolidate old messages into memory.md when history exceeds the threshold
    - Persist new exchanges after each agent turn
    """

    def __init__(
        self,
        storage: MemoryPort,
        skills: SkillsPort | None = None,
        llm: LLMPort | None = None,
        consolidation_threshold: int = 100,
        keep_recent_ratio: float = 0.2,
    ) -> None:
        """
        Args:
            storage: The persistence adapter implementing MemoryPort.
            skills: Optional skills loader. If provided, injects skill metadata
                    and always-skill bodies into every system prompt.
            llm: Optional LLM adapter for history consolidation. If None,
                 consolidation is disabled.
            consolidation_threshold: Number of messages that triggers consolidation.
            keep_recent_ratio: Fraction of consolidation_threshold to keep verbatim
                               after consolidation (e.g. 0.2 = 20%).
        """
        self._storage = storage
        self._skills = skills
        self._llm = llm
        self._consolidation_threshold = consolidation_threshold
        self._keep_recent = max(1, int(consolidation_threshold * keep_recent_ratio))

    async def build_messages(
        self,
        session_id: str,
        system_prompt: str,
        user_message: str,
    ) -> list[Message]:
        """
        Construct the full message list for an LLM call.

        Layout: [system_prompt + memory.md + skills + optional warning] + [history] + [user_message]

        Args:
            session_id: Unique session identifier.
            system_prompt: The base system prompt (AGENTS.md content).
            user_message: The current user input.

        Returns:
            Ordered list of messages ready to send to the LLM.
        """
        global_memory = await self._storage.load_global_memory()
        session_summary = await self._storage.load_session_summary(session_id)
        history = await self._storage.load_history(session_id)

        # Load cursor once; used for trigger check, warning check, and consolidation
        cursor = await self._storage.load_consolidated_cursor(session_id)

        # Consolidate history if unconsolidated messages exceed threshold and LLM available
        if len(history) - cursor > self._consolidation_threshold and self._llm is not None:
            history = await self._consolidate(session_id, history, cursor)
            # Reload session_summary so the freshly written summary appears in the system prompt
            session_summary = await self._storage.load_session_summary(session_id)

        # Build system prompt with global memory and session summary appended
        full_system = system_prompt
        if global_memory.strip():
            full_system += f"\n\n## Your Memory\n\n{global_memory}"
        if session_summary.strip():
            full_system += f"\n\n## Session Summary\n\n{session_summary}"

        # Inject skills: XML index + full bodies of always-skills
        if self._skills is not None:
            from squidbot.core.skills import build_skills_xml  # noqa: PLC0415

            skill_list = self._skills.list_skills()
            full_system += f"\n\n{build_skills_xml(skill_list)}"
            for skill in skill_list:
                if skill.always and skill.available:
                    body = self._skills.load_skill_body(skill.name)
                    full_system += f"\n\n{body}"

        # Warn the agent one or two turns before consolidation fires
        if len(history) - cursor >= self._consolidation_threshold - 2:
            full_system += _CONSOLIDATION_WARNING

        messages: list[Message] = [
            Message(role="system", content=full_system),
            *history,
            Message(role="user", content=user_message),
        ]
        return messages

    async def persist_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_reply: str,
    ) -> None:
        """
        Save a completed user–assistant exchange to history.

        Only the user message and the final assistant text reply are persisted.
        Intermediate tool-call and tool-result messages are not stored.

        # TODO: persist tool-call/tool-result pairs so the agent regains full
        # tool context after a restart. Requires storing complete assistant+tool
        # message sequences (OpenAI format requires paired turns) and handling
        # partial sequences from mid-round crashes gracefully.

        Args:
            session_id: Unique session identifier.
            user_message: The user's input text.
            assistant_reply: The final text response from the assistant.
        """
        await self._storage.append_message(session_id, Message(role="user", content=user_message))
        await self._storage.append_message(
            session_id, Message(role="assistant", content=assistant_reply)
        )

    async def append_tool_event(
        self,
        session_id: str,
        call_text: str,
        result_text: str,
    ) -> None:
        """
        Persist a tool call and its result as two searchable JSONL messages.

        These messages use the custom roles "tool_call" and "tool_result" which
        are never sent to the LLM API — they are filtered out in build_messages.
        They are searchable via search_history.

        Args:
            session_id: Unique session identifier.
            call_text: Human-readable call string, e.g. "shell(cmd='ls -la')".
            result_text: Tool output (pre-truncated by the caller).
        """
        await self._storage.append_message(session_id, Message(role="tool_call", content=call_text))
        await self._storage.append_message(
            session_id, Message(role="tool_result", content=result_text)
        )

    async def _call_llm(self, messages: list[Message], *, context: str = "llm") -> str | None:
        """
        Call the LLM with the given messages and return the full response text.

        Streams the response, joins all text chunks, and returns the stripped result.
        Returns None if the LLM raises an exception or yields an empty response.
        Logs a warning on exception, including the context label for traceability.

        Precondition: self._llm is not None (caller must verify).

        Args:
            messages: The messages to send to the LLM.
            context: Label included in the warning log to identify which operation failed
                     (e.g. "consolidation", "meta-consolidation").

        Returns:
            Stripped response text, or None on failure or empty response.
        """
        llm = self._llm
        assert llm is not None  # noqa: S101 — narrowing for type checker
        try:
            chunks: list[str] = []
            response_stream = await llm.chat(messages, [])
            async for chunk in response_stream:
                if isinstance(chunk, str):
                    chunks.append(chunk)
            result = "".join(chunks).strip()
            return result or None
        except Exception as e:
            from loguru import logger  # noqa: PLC0415

            logger.warning("{} LLM call failed: {}", context, e)
            return None

    async def _maybe_meta_consolidate(self, summary: str) -> str:
        """
        Compress the session summary via LLM if it exceeds the word limit.

        If the summary is within _META_SUMMARY_WORD_LIMIT words, returns it unchanged
        (fast path, no LLM call). Otherwise calls the LLM with a meta-consolidation
        prompt to produce a compressed version of approximately _META_SUMMARY_SENTENCES
        sentences. On LLM failure, returns the original summary unchanged (graceful
        degradation — data loss avoided at the cost of a large summary).

        Args:
            summary: The current session summary text.

        Returns:
            Compressed summary text, or original summary if within limit, no LLM
            available, or on failure.
        """
        if self._llm is None or len(summary.split()) <= _META_SUMMARY_WORD_LIMIT:
            return summary
        messages = [
            Message(role="system", content=_META_CONSOLIDATION_SYSTEM),
            Message(
                role="user",
                content=_META_CONSOLIDATION_PROMPT.format(
                    summary=summary,
                    sentences=_META_SUMMARY_SENTENCES,
                ),
            ),
        ]
        result = await self._call_llm(messages, context="meta-consolidation")
        return result if result else summary

    async def _consolidate(
        self, session_id: str, history: list[Message], cursor: int
    ) -> list[Message]:
        """
        Summarize unconsolidated messages and append to memory.md, returning recent messages.

        Only summarizes messages[cursor:-keep_recent]. Advances cursor after success.

        Args:
            session_id: Unique session identifier.
            history: Full message history.
            cursor: The already-loaded consolidation cursor (last consolidated message index).

        Returns:
            Only the recent messages to keep in context.
        """
        recent = history[-self._keep_recent :]
        to_summarize = history[cursor : -self._keep_recent]

        if not to_summarize:
            return recent

        # Build text from user/assistant messages only
        history_text = ""
        for msg in to_summarize:
            if msg.role in ("user", "assistant"):
                history_text += f"{msg.role}: {msg.content}\n"

        if not history_text.strip():
            return recent

        # Call LLM for summary (self._llm is non-None; caller guarantees this)
        sentence_budget = max(5, len(to_summarize) // 10)
        prompt = _CONSOLIDATION_PROMPT.format(history=history_text, sentences=sentence_budget)
        summary_messages = [
            Message(role="system", content=_CONSOLIDATION_SYSTEM),
            Message(role="user", content=prompt),
        ]
        summary = await self._call_llm(summary_messages, context="consolidation")
        if not summary:
            return recent

        # Append to existing session summary
        existing = await self._storage.load_session_summary(session_id)
        updated = f"{existing}\n\n{summary}" if existing.strip() else summary
        updated = await self._maybe_meta_consolidate(updated)
        try:
            await self._storage.save_session_summary(session_id, updated)
            new_cursor = len(history) - self._keep_recent
            await self._storage.save_consolidated_cursor(session_id, new_cursor)
        except Exception as e:
            from loguru import logger  # noqa: PLC0415

            logger.warning("Failed to save consolidation summary, skipping: {}", e)
            return recent

        return recent
