"""
Core memory manager for squidbot.

Coordinates short-term (in-session history) and long-term (memory.md) memory.
The manager is pure domain logic — it takes a MemoryPort as dependency
and contains no I/O or external service calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from squidbot.core.models import Message
from squidbot.core.ports import MemoryPort, SkillsPort

if TYPE_CHECKING:
    from squidbot.core.ports import LLMPort

# Injected into the system prompt when the context limit is approaching.
_PRUNE_WARNING = (
    "\n\n[System: Conversation history is long. Important information will be "
    "dropped soon. Use the memory_write tool to preserve anything critical before "
    "it leaves context.]\n"
)

_CONSOLIDATION_PROMPT = (
    "Summarize the following conversation history into a concise memory entry. "
    "Focus on key facts, decisions, and context useful for future conversations. "
    "Do not include small talk or filler.\n\n"
    "Conversation history:\n{history}\n\n"
    "Provide a brief summary (2-5 sentences) suitable for appending to a memory document."
)


class MemoryManager:
    """
    Manages message history and memory documents for agent sessions.

    Responsibilities:
    - Build the full message list for each LLM call (system + history + user)
    - Inject memory.md content into the system prompt
    - Inject skills XML block and always-skill bodies into the system prompt
    - Prune old messages when history exceeds the configured limit
    - Persist new exchanges after each agent turn
    """

    def __init__(
        self,
        storage: MemoryPort,
        max_history_messages: int = 200,
        skills: SkillsPort | None = None,
        llm: LLMPort | None = None,
        consolidation_threshold: int = 100,
        keep_recent: int = 20,
    ) -> None:
        """
        Args:
            storage: The persistence adapter implementing MemoryPort.
            max_history_messages: Maximum number of history messages to keep.
                                  Older messages are dropped (not summarized).
            skills: Optional skills loader. If provided, injects skill metadata
                    and always-skill bodies into every system prompt.
            llm: Optional LLM adapter for history consolidation. If None,
                 consolidation is disabled.
            consolidation_threshold: Number of messages that triggers consolidation.
            keep_recent: Number of recent messages to keep verbatim during
                         consolidation.
        """
        self._storage = storage
        self._max_history = max_history_messages
        self._skills = skills
        self._llm = llm
        self._consolidation_threshold = consolidation_threshold
        self._keep_recent = keep_recent
        self._warn_threshold = int(max_history_messages * 0.8)

    async def build_messages(
        self,
        session_id: str,
        system_prompt: str,
        user_message: str,
    ) -> list[Message]:
        """
        Construct the full message list for an LLM call.

        Layout: [system_prompt + memory.md + skills] + [history (pruned)] + [user_message]

        Args:
            session_id: Unique session identifier.
            system_prompt: The base system prompt (AGENTS.md content).
            user_message: The current user input.

        Returns:
            Ordered list of messages ready to send to the LLM.
        """
        memory_doc = await self._storage.load_memory_doc(session_id)
        history = await self._storage.load_history(session_id)

        # Build system prompt with memory document appended
        full_system = system_prompt
        if memory_doc.strip():
            full_system += f"\n\n## Your Memory\n\n{memory_doc}"

        # Inject skills: XML index + full bodies of always-skills
        if self._skills is not None:
            from squidbot.core.skills import build_skills_xml  # noqa: PLC0415

            skill_list = self._skills.list_skills()
            full_system += f"\n\n{build_skills_xml(skill_list)}"
            for skill in skill_list:
                if skill.always and skill.available:
                    body = self._skills.load_skill_body(skill.name)
                    full_system += f"\n\n{body}"

        # Consolidate history if over threshold and LLM available
        if len(history) > self._consolidation_threshold and self._llm is not None:
            history = await self._consolidate(session_id, history)

        # Prune history if over the limit
        near_limit = len(history) >= self._warn_threshold
        if len(history) > self._max_history:
            history = history[-self._max_history :]

        # Inject warning when approaching the limit
        if near_limit:
            full_system += _PRUNE_WARNING

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
        Summarize old messages and append to memory.md, returning recent messages.

        Takes messages[:-keep_recent] to summarize, keeps [-keep_recent:] verbatim.

        Args:
            session_id: Unique session identifier.
            history: Full message history.

        Returns:
            Only the recent messages to keep in context.
        """
        assert self._llm is not None  # Already checked in build_messages

        to_summarize = history[: -self._keep_recent]
        recent = history[-self._keep_recent :]

        # Build text from user/assistant messages only
        history_text = ""
        for msg in to_summarize:
            if msg.role in ("user", "assistant"):
                history_text += f"{msg.role}: {msg.content}\n"

        if not history_text.strip():
            return recent

        # Call LLM for summary
        prompt = _CONSOLIDATION_PROMPT.format(history=history_text)
        summary_gen = await self._llm.chat(
            messages=[Message(role="user", content=prompt)],
            tools=[],
        )
        summary_parts: list[str] = []
        async for chunk in summary_gen:
            if isinstance(chunk, str):
                summary_parts.append(chunk)
        summary = "".join(summary_parts)

        # Append to existing memory.md
        existing = await self._storage.load_memory_doc(session_id)
        updated = f"{existing}\n\n{summary}" if existing.strip() else summary
        await self._storage.save_memory_doc(session_id, updated)

        return recent
