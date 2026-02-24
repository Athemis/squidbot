"""
Core memory manager for squidbot.

Coordinates global cross-channel history, long-term memory (MEMORY.md), and
global consolidation summaries. The manager is pure domain logic — it takes a
MemoryPort as dependency and contains no I/O or external service calls.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from squidbot.core.models import Message
from squidbot.core.ports import MemoryPort, SkillsPort

if TYPE_CHECKING:
    from squidbot.config.schema import OwnerAliasEntry
    from squidbot.core.ports import LLMPort

ContextBudgetMode = Literal["words", "tokens"]

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
    "You are given an existing conversation summary that has grown too long. "
    "Compress it into a shorter summary that retains all facts, decisions, and context. "
    "Output only the summary text — no preamble, no commentary, no formatting."
)

_META_CONSOLIDATION_PROMPT = (
    "The following is a conversation summary that has grown too long and needs to be compressed."
    "\n\n"
    "{summary}\n\n"
    "Rewrite this as a compact summary of approximately {sentences} sentences. "
    "Retain all facts, decisions, and context. Do not discard any information."
)

_META_SUMMARY_WORD_LIMIT = 600
_META_SUMMARY_SENTENCES = 8
_SUMMARY_BULLET_PREFIXES: tuple[str, ...] = ("-", "*")
_MEMORY_HEADING_WORDS = 3
_SUMMARY_HEADING_WORDS = 3


class MemoryManager:
    """
    Manages global message history and memory documents for the agent.

    Responsibilities:
    - Build the full message list for each LLM call (system + labelled history + user)
    - Inject global memory.md content into the system prompt
    - Inject skills XML block and always-skill bodies into the system prompt
    - Label history messages with channel/sender context, identifying the owner
    - Warn the agent one turn before consolidation via _CONSOLIDATION_WARNING
    - Consolidate old messages into the global summary when history exceeds the threshold
    - Persist new exchanges after each agent turn with channel and sender_id metadata
    """

    def __init__(
        self,
        storage: MemoryPort,
        skills: SkillsPort | None = None,
        llm: LLMPort | None = None,
        owner_aliases: list[OwnerAliasEntry] | None = None,
        consolidation_threshold: int = 100,
        keep_recent_ratio: float = 0.2,
        context_budget_mode: ContextBudgetMode = "words",
        context_memory_max_words: int = 300,
        context_summary_max_words: int = 500,
        context_history_max_words: int = 2500,
        context_total_max_words: int = 4500,
        context_dedupe_summary_against_memory: bool = True,
        context_min_recent_messages: int = 2,
        context_token_counter: Callable[[str], int] | None = None,
    ) -> None:
        """
        Args:
            storage: The persistence adapter implementing MemoryPort.
            skills: Optional skills loader. If provided, injects skill metadata
                    and always-skill bodies into every system prompt.
            llm: Optional LLM adapter for history consolidation. If None,
                 consolidation is disabled.
            owner_aliases: List of owner alias entries used to identify the owner
                           in labelled history. Unscoped aliases match any channel;
                           scoped aliases only match their specified channel.
            consolidation_threshold: Number of messages that triggers consolidation.
            keep_recent_ratio: Fraction of consolidation_threshold to keep verbatim
                               after consolidation (e.g. 0.2 = 20%).
            context_budget_mode: Context budget strategy. "tokens" currently
                                 requires an injected token counter; otherwise
                                 it falls back to words mode.
            context_memory_max_words: Max words kept in the memory block.
            context_summary_max_words: Max words kept in the summary block.
            context_history_max_words: Max words kept in labelled history.
            context_total_max_words: Max words for system context + history.
            context_dedupe_summary_against_memory: Remove summary lines already
                                                   present in memory.
            context_min_recent_messages: Minimum newest history messages to keep
                                         even when history word budget is tight.
            context_token_counter: Optional token-counting function for future
                                   token budget mode.
        """
        self._storage = storage
        self._skills = skills
        self._llm = llm
        self._owner_aliases: list[OwnerAliasEntry] = owner_aliases or []
        self._consolidation_threshold = consolidation_threshold
        self._keep_recent = max(1, int(consolidation_threshold * keep_recent_ratio))
        self._context_budget_mode: ContextBudgetMode = context_budget_mode
        self._context_memory_max_words = context_memory_max_words
        self._context_summary_max_words = context_summary_max_words
        self._context_history_max_words = context_history_max_words
        self._context_total_max_words = context_total_max_words
        self._context_dedupe_summary_against_memory = context_dedupe_summary_against_memory
        self._context_min_recent_messages = context_min_recent_messages
        self._context_token_counter = context_token_counter
        self._token_fallback_warned = False

    def _is_owner(self, sender_id: str, channel: str) -> bool:
        """
        Return True if sender_id matches an owner alias for the given channel.

        First checks channel-scoped aliases (entry.channel == channel and
        entry.address == sender_id), then unscoped aliases (entry.channel is None
        and entry.address == sender_id). Case-sensitive.

        Args:
            sender_id: The sender identifier to check.
            channel: The channel the message was sent in.

        Returns:
            True if any alias matches, False otherwise.
        """
        # Channel-scoped check first
        for entry in self._owner_aliases:
            if entry.channel == channel and entry.address == sender_id:
                return True
        # Unscoped check
        for entry in self._owner_aliases:
            if entry.channel is None and entry.address == sender_id:
                return True
        return False

    def _label_message(self, msg: Message) -> Message:
        """
        Return a copy of msg with a channel/sender label prepended to content.

        Skips labelling if msg.channel is None (legacy messages without channel info).
        The label format is: "[{channel} / {label}]\\n{content}" where label is
        "owner" if the sender is identified as the owner, else the sender_id
        (or "unknown" if sender_id is None).

        Args:
            msg: The message to label.

        Returns:
            A new Message with the label prefix, or the original if no channel.
        """
        if msg.channel is None:
            return msg
        if msg.sender_id == "assistant":
            label = "assistant"
        elif self._is_owner(msg.sender_id or "", msg.channel):
            label = "owner"
        else:
            label = msg.sender_id or "unknown"
        new_content = f"[{msg.channel} / {label}]\n{msg.content}"
        return Message(
            role=msg.role,
            content=new_content,
            tool_calls=msg.tool_calls,
            tool_call_id=msg.tool_call_id,
            timestamp=msg.timestamp,
            channel=msg.channel,
            sender_id=msg.sender_id,
        )

    def _normalize_line_for_dedupe(self, line: str) -> str:
        """Normalize a summary/memory line for deterministic de-duplication."""
        normalized = " ".join(line.strip().lower().split())
        if not normalized:
            return ""
        for prefix in _SUMMARY_BULLET_PREFIXES:
            if normalized.startswith(prefix):
                normalized = normalized.removeprefix(prefix).strip()
        return normalized

    def _dedupe_summary_against_memory(self, memory: str, summary: str) -> tuple[str, int]:
        """Remove summary lines that are exact normalized duplicates of memory lines."""
        memory_lines = {
            normalized
            for line in memory.splitlines()
            if (normalized := self._normalize_line_for_dedupe(line))
        }
        kept: list[str] = []
        removed = 0
        for line in summary.splitlines():
            normalized = self._normalize_line_for_dedupe(line)
            if not normalized:
                continue
            if normalized in memory_lines:
                removed += 1
                continue
            kept.append(line)
        return "\n".join(kept), removed

    def _truncate_words(self, text: str, max_words: int) -> str:
        """Return text truncated to at most max_words words."""
        words = text.split()
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words])

    def _message_word_count(self, msg: Message) -> int:
        """Return approximate word cost of a labelled history message."""
        return len(msg.content.split())

    def _take_recent_history_by_word_budget(
        self,
        history: list[Message],
        max_words: int,
        min_recent_messages: int,
    ) -> list[Message]:
        """Keep recent history within a word budget while preserving chronology."""
        if not history:
            return []
        floor = max(1, min(min_recent_messages, len(history)))
        kept_rev: list[Message] = []
        used_words = 0

        for msg in reversed(history[-floor:]):
            kept_rev.append(msg)
            used_words += self._message_word_count(msg)

        for msg in reversed(history[:-floor]):
            msg_words = self._message_word_count(msg)
            if used_words + msg_words > max_words:
                break
            kept_rev.append(msg)
            used_words += msg_words
        return list(reversed(kept_rev))

    def _context_blocks_word_count(
        self,
        memory: str,
        summary: str,
        history: list[Message],
    ) -> int:
        """Count words in compacted context blocks (memory, summary, history)."""
        words = sum(self._message_word_count(msg) for msg in history)
        if memory.strip():
            words += _MEMORY_HEADING_WORDS + len(memory.split())
        if summary.strip():
            words += _SUMMARY_HEADING_WORDS + len(summary.split())
        return words

    def _enforce_total_word_budget(
        self,
        memory: str,
        summary: str,
        history: list[Message],
        max_words: int,
        min_recent_messages: int,
    ) -> tuple[str, str, list[Message]]:
        """Trim context blocks to respect a total word budget."""
        min_keep = min(min_recent_messages, len(history))
        while (
            self._context_blocks_word_count(memory, summary, history) > max_words
            and len(history) > min_keep
        ):
            history = history[1:]

        total_words = self._context_blocks_word_count(memory, summary, history)
        if total_words > max_words and summary.strip():
            summary_words = len(summary.split())
            excess_words = total_words - max_words
            summary = self._truncate_words(summary, max(0, summary_words - excess_words))
            total_words = self._context_blocks_word_count(memory, summary, history)

        if total_words > max_words and memory.strip():
            memory_words = len(memory.split())
            memory = self._truncate_words(memory, max(0, memory_words - (total_words - max_words)))

        return memory, summary, history

    def _resolve_context_budget_mode(self) -> ContextBudgetMode:
        """Return the active budget mode; fallback to words when tokens mode is unavailable."""
        if self._context_budget_mode == "tokens" and self._context_token_counter is None:
            if not self._token_fallback_warned:
                from loguru import logger  # noqa: PLC0415

                logger.warning(
                    "context_budget_mode=tokens requested without token counter; "
                    "falling back to words mode."
                )
                self._token_fallback_warned = True
            return "words"
        return self._context_budget_mode

    async def build_messages(
        self,
        channel: str,
        sender_id: str,
        user_message: str,
        system_prompt: str,
    ) -> list[Message]:
        """
        Construct the full message list for an LLM call.

        Layout: [system_prompt + memory + summary + skills + optional warning]
                + [labelled_history] + [user_message]

        Args:
            channel: The channel this message came in on.
            sender_id: The sender identifier for this message.
            user_message: The current user input.
            system_prompt: The base system prompt (AGENTS.md content).

        Returns:
            Ordered list of messages ready to send to the LLM.
        """
        load_n = self._consolidation_threshold + self._keep_recent
        all_history = await self._storage.load_history()
        history = all_history[-load_n:]
        global_memory = await self._storage.load_global_memory()
        global_summary = await self._storage.load_global_summary()

        # Load cursor once; used for trigger check, warning check, and consolidation
        cursor = await self._storage.load_global_cursor()
        unconsolidated_count = len(all_history) - cursor

        # Consolidate history if unconsolidated messages exceed threshold and LLM available
        if unconsolidated_count > self._consolidation_threshold and self._llm is not None:
            history = await self._consolidate(all_history, cursor)
            # Reload summary so the freshly written summary appears in the system prompt
            global_summary = await self._storage.load_global_summary()
            cursor = await self._storage.load_global_cursor()
            unconsolidated_count = len(all_history) - cursor

        budget_mode = self._resolve_context_budget_mode()
        if budget_mode == "tokens":
            # Token budgeting is intentionally deferred; use deterministic word mode for now.
            budget_mode = "words"

        deduped_lines = 0
        if budget_mode == "words":
            if self._context_dedupe_summary_against_memory:
                global_summary, deduped_lines = self._dedupe_summary_against_memory(
                    global_memory,
                    global_summary,
                )
            global_memory = self._truncate_words(global_memory, self._context_memory_max_words)
            global_summary = self._truncate_words(global_summary, self._context_summary_max_words)

        # Label each history message with channel/sender context
        labelled_history = [self._label_message(msg) for msg in history]
        if budget_mode == "words":
            labelled_history = self._take_recent_history_by_word_budget(
                history=labelled_history,
                max_words=self._context_history_max_words,
                min_recent_messages=self._context_min_recent_messages,
            )
            global_memory, global_summary, labelled_history = self._enforce_total_word_budget(
                memory=global_memory,
                summary=global_summary,
                history=labelled_history,
                max_words=self._context_total_max_words,
                min_recent_messages=self._context_min_recent_messages,
            )

            from loguru import logger  # noqa: PLC0415

            logger.debug(
                "context budget applied: mode={}, deduped_summary_lines={}, memory_words={}, "
                "summary_words={}, history_words={}, history_messages={}",
                budget_mode,
                deduped_lines,
                len(global_memory.split()),
                len(global_summary.split()),
                sum(self._message_word_count(msg) for msg in labelled_history),
                len(labelled_history),
            )

        # Build system prompt with global memory and conversation summary appended
        full_system = system_prompt
        if global_memory.strip():
            full_system += f"\n\n## Your Memory\n\n{global_memory}"
        if global_summary.strip():
            full_system += f"\n\n## Conversation Summary\n\n{global_summary}"

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
        if unconsolidated_count >= self._consolidation_threshold - 2:
            full_system += _CONSOLIDATION_WARNING

        messages: list[Message] = [
            Message(role="system", content=full_system),
            *labelled_history,
            Message(role="user", content=user_message),
        ]
        return messages

    async def persist_exchange(
        self,
        channel: str,
        sender_id: str,
        user_message: str,
        assistant_reply: str,
    ) -> None:
        """
        Save a completed user–assistant exchange to global history.

        Only the user message and the final assistant text reply are persisted.
        Intermediate tool-call and tool-result messages are not stored.

        # TODO: persist tool-call/tool-result pairs so the agent regains full
        # tool context after a restart. Requires storing complete assistant+tool
        # message sequences (OpenAI format requires paired turns) and handling
        # partial sequences from mid-round crashes gracefully.

        Args:
            channel: The channel this exchange occurred on.
            sender_id: The sender identifier for the user message.
            user_message: The user's input text.
            assistant_reply: The final text response from the assistant.
        """
        await self._storage.append_message(
            Message(role="user", content=user_message, channel=channel, sender_id=sender_id)
        )
        await self._storage.append_message(
            Message(
                role="assistant", content=assistant_reply, channel=channel, sender_id="assistant"
            )
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
        Compress the global summary via LLM if it exceeds the word limit.

        If the summary is within _META_SUMMARY_WORD_LIMIT words, returns it unchanged
        (fast path, no LLM call). Otherwise calls the LLM with a meta-consolidation
        prompt to produce a compressed version of approximately _META_SUMMARY_SENTENCES
        sentences. On LLM failure, returns the original summary unchanged (graceful
        degradation — data loss avoided at the cost of a large summary).

        Args:
            summary: The current global summary text.

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

    async def _consolidate(self, history: list[Message], cursor: int) -> list[Message]:
        """
        Summarize unconsolidated messages and save to global summary, returning recent messages.

        Only summarizes messages[cursor:-keep_recent]. Advances global cursor after success.

        Args:
            history: Full global message history.
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

        # Append to existing global summary
        existing = await self._storage.load_global_summary()
        updated = f"{existing}\n\n{summary}" if existing.strip() else summary
        updated = await self._maybe_meta_consolidate(updated)
        try:
            await self._storage.save_global_summary(updated)
            new_cursor = len(history) - self._keep_recent
            await self._storage.save_global_cursor(new_cursor)
        except Exception as e:
            from loguru import logger  # noqa: PLC0415

            logger.warning("Failed to save consolidation summary, skipping: {}", e)
            return recent

        return recent
