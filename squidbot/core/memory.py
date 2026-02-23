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

_SUMMARY_WORD_LIMIT = 600
_SUMMARY_KEEP_PARAGRAPHS = 8


def _trim_summary(text: str) -> str:
    """
    Trim a session summary if it exceeds the word limit.

    Keeps the last _SUMMARY_KEEP_PARAGRAPHS non-empty paragraphs so the most
    recent consolidation cycles are preserved. No-ops when within limits.

    Args:
        text: The full session summary text.

    Returns:
        The (possibly trimmed) summary text.
    """
    if len(text.split()) <= _SUMMARY_WORD_LIMIT:
        return text
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    return "\n\n".join(paragraphs[-_SUMMARY_KEEP_PARAGRAPHS:])


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

        # Load cursor once; used for both trigger and warning checks below
        cursor = await self._storage.load_consolidated_cursor(session_id)

        # Consolidate history if unconsolidated messages exceed threshold and LLM available
        if len(history) - cursor > self._consolidation_threshold and self._llm is not None:
            history = await self._consolidate(session_id, history)
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

        Tool calls/results within the exchange are handled by the agent loop
        and appended separately via append_message.

        Args:
            session_id: Unique session identifier.
            user_message: The user's input text.
            assistant_reply: The final text response from the assistant.
        """
        await self._storage.append_message(session_id, Message(role="user", content=user_message))
        await self._storage.append_message(
            session_id, Message(role="assistant", content=assistant_reply)
        )

    async def _consolidate(self, session_id: str, history: list[Message]) -> list[Message]:
        """
        Summarize unconsolidated messages and append to memory.md, returning recent messages.

        Only summarizes messages[cursor:-keep_recent]. Advances cursor after success.

        Args:
            session_id: Unique session identifier.
            history: Full message history.

        Returns:
            Only the recent messages to keep in context.
        """
        cursor = await self._storage.load_consolidated_cursor(session_id)
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
        llm = self._llm
        assert llm is not None  # noqa: S101 — narrowing for type checker
        sentence_budget = max(5, len(to_summarize) // 10)
        prompt = _CONSOLIDATION_PROMPT.format(history=history_text, sentences=sentence_budget)
        summary_messages = [
            Message(role="system", content=_CONSOLIDATION_SYSTEM),
            Message(role="user", content=prompt),
        ]
        try:
            summary_chunks: list[str] = []
            response_stream = await llm.chat(summary_messages, [])
            async for chunk in response_stream:
                if isinstance(chunk, str):
                    summary_chunks.append(chunk)
            summary = "".join(summary_chunks).strip()
        except Exception as e:
            from loguru import logger  # noqa: PLC0415

            logger.warning("Consolidation LLM call failed, skipping: {}", e)
            return recent

        if not summary:
            return recent

        # Append to existing session summary
        existing = await self._storage.load_session_summary(session_id)
        updated = f"{existing}\n\n{summary}" if existing.strip() else summary
        updated = _trim_summary(updated)
        try:
            await self._storage.save_session_summary(session_id, updated)
            new_cursor = len(history) - self._keep_recent
            await self._storage.save_consolidated_cursor(session_id, new_cursor)
        except Exception as e:
            from loguru import logger  # noqa: PLC0415

            logger.warning("Failed to save consolidation summary, skipping: {}", e)
            return recent

        return recent
