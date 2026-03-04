"""
Core memory manager for squidbot.

Coordinates global cross-channel history and long-term memory (MEMORY.md).
The manager is pure domain logic — it takes a MemoryPort as dependency and
contains no I/O or external service calls.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from squidbot.core.models import Message, Session
from squidbot.core.ports import MemoryPort, SkillsPort
from squidbot.core.skills import build_skills_xml

if TYPE_CHECKING:
    from squidbot.config.schema import OwnerAliasEntry


class MemoryManager:
    """
    Manages global message history and memory documents for the agent.

    Responsibilities:
     - Build the full message list for each LLM call (system + labelled history + user)
     - Inject global memory.md content into the system prompt
     - Inject skills XML block and always-skill bodies into the system prompt
     - Label history messages with channel/sender context, identifying the owner
     - Limit history context to a configured number of recent messages
     - Persist new exchanges after each agent turn with channel and sender_id metadata
    """

    def __init__(
        self,
        storage: MemoryPort,
        skills: SkillsPort | None = None,
        owner_aliases: list[OwnerAliasEntry] | None = None,
        history_context_messages: int = 80,
    ) -> None:
        """
        Args:
            storage: The persistence adapter implementing MemoryPort.
            skills: Optional skills loader. If provided, injects skill metadata
                    and always-skill bodies into every system prompt.
            owner_aliases: List of owner alias entries used to identify the owner
                           in labelled history. Unscoped aliases match any channel;
                           scoped aliases only match their specified channel.
            history_context_messages: Number of recent history messages to include
                                      in context for each prompt.
        """
        self._storage = storage
        self._skills = skills
        self._owner_aliases: list[OwnerAliasEntry] = owner_aliases or []
        self._scoped_aliases: set[tuple[str, str]] = set()
        self._unscoped_aliases: set[str] = set()
        for entry in self._owner_aliases:
            channel = entry.channel
            if channel:
                self._scoped_aliases.add((entry.address, channel))
            else:
                self._unscoped_aliases.add(entry.address)

        if history_context_messages <= 0:
            raise ValueError("history_context_messages must be > 0")
        self._history_context_messages = history_context_messages

        # Cache for the assembled skills block.
        # Key: frozenset of (name, location_str, available, always, description, mtime) tuples.
        # Value: the assembled XML + always-skill bodies string.
        self._skills_cache: (
            tuple[frozenset[tuple[str, str, bool, bool, str, float]], str] | None
        ) = None

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
        if (sender_id, channel) in self._scoped_aliases:
            return True
        return sender_id in self._unscoped_aliases

    def is_owner_sender(self, sender_id: str | None, channel: str) -> bool:
        """Return True when sender is authorized as owner for a channel.

        CLI is always authorized because physical host access implies owner control.
        For non-CLI channels, owner aliases are required.

        Args:
            sender_id: Sender identifier resolved by the channel loop.
            channel: Channel name for scoped alias matching.

        Returns:
            True when the sender is treated as owner for policy checks.
        """
        if channel == "cli":
            return True
        if sender_id is None:
            return False
        return self._is_owner(sender_id, channel)

    async def load_global_memory_text(self) -> str:
        """Return current global memory document text."""
        return await self._storage.load_global_memory()

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
        # Assistant messages do not need a label — the LLM already knows they are
        # its own prior responses. Labelling them causes the model to mimic the
        # prefix format in new replies.
        if msg.sender_id == "assistant":
            return msg
        if self._is_owner(msg.sender_id or "", msg.channel):
            label = "owner"
        else:
            label = msg.sender_id or "unknown"
        new_content = f"[{msg.channel} / {label}]\n{msg.content}"
        return Message(
            role=msg.role,
            content=new_content,
            tool_calls=msg.tool_calls,
            tool_call_id=msg.tool_call_id,
            reasoning_content=msg.reasoning_content,
            timestamp=msg.timestamp,
            channel=msg.channel,
            sender_id=msg.sender_id,
            session_id=msg.session_id,
        )

    async def build_messages(
        self,
        user_message: str,
        system_prompt: str,
        session: Session | None = None,
        *,
        session_id: str | None = None,
        load_history: bool = True,
    ) -> list[Message]:
        """
        Construct the full message list for an LLM call.

        Layout: [system_prompt + memory + skills]
                + [labelled_history] + [user_message]

        Args:
            user_message: The current user input.
            system_prompt: The base system prompt (AGENTS.md content).
            session: Optional physical session for legacy matching fallback.
            session_id: Optional logical session ID used for history selection.
            load_history: Whether to inject history into the prompt.

        Returns:
            Ordered list of messages ready to send to the LLM.
        """
        if load_history:
            history, global_memory = await asyncio.gather(
                self._storage.load_history(last_n=self._history_context_messages),
                self._storage.load_global_memory(),
            )
        else:
            history = []
            global_memory = await self._storage.load_global_memory()

        if load_history:
            target_session_id = session_id or (session.id if session is not None else None)
            if target_session_id is not None:
                history = self._filter_history_for_session(
                    history,
                    target_session_id=target_session_id,
                    fallback_session=session,
                )

        # Label each history message with channel/sender context
        labelled_history = [self._label_message(msg) for msg in history]

        # Assemble the system prompt using a list to avoid repeated string concatenation
        system_parts: list[str] = [system_prompt]
        if global_memory.strip():
            system_parts.append(f"## Your Memory\n\n{global_memory}")

        # Inject skills: XML index + full bodies of always-skills (cached by fingerprint)
        if self._skills is not None:
            skill_list = self._skills.list_skills()
            # mtime is included so that changes to an always-skill's body (which
            # FsSkillsLoader tracks by mtime) also invalidate this cache.
            fingerprint = frozenset(
                (s.name, str(s.location), s.available, s.always, s.description, s.mtime)
                for s in skill_list
            )

            if self._skills_cache is None or self._skills_cache[0] != fingerprint:
                parts: list[str] = [build_skills_xml(skill_list)]
                for skill in skill_list:
                    if skill.always and skill.available:
                        parts.append(self._skills.load_skill_body(skill.name))
                self._skills_cache = (fingerprint, "\n\n".join(parts))

            system_parts.append(self._skills_cache[1])

        full_system = "\n\n".join(system_parts)

        messages: list[Message] = [
            Message(role="system", content=full_system),
            *labelled_history,
            Message(role="user", content=user_message),
        ]
        return messages

    def _filter_history_for_session(
        self,
        history: list[Message],
        *,
        target_session_id: str,
        fallback_session: Session | None,
    ) -> list[Message]:
        """Filter history to rows that belong to the logical session."""
        filtered: list[Message] = []
        for msg in history:
            if self._history_matches_session(
                msg,
                target_session_id=target_session_id,
                fallback_session=fallback_session,
            ):
                filtered.append(msg)
        return filtered

    def _history_matches_session(
        self,
        msg: Message,
        *,
        target_session_id: str,
        fallback_session: Session | None,
    ) -> bool:
        """Return True when a history row belongs to the logical session."""
        if msg.session_id is not None:
            return msg.session_id == target_session_id
        if fallback_session is None:
            return False
        if target_session_id != fallback_session.id:
            return False
        return self._is_legacy_session_match(msg, fallback_session)

    def _is_legacy_session_match(self, msg: Message, session: Session) -> bool:
        """Best-effort matching for older history entries without session_id."""
        if msg.channel != session.channel:
            return False
        if msg.role == "assistant":
            return True
        return msg.sender_id == session.sender_id

    async def persist_exchange(
        self,
        channel: str,
        sender_id: str,
        user_message: str,
        assistant_reply: str,
        session_id: str,
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
            session_id: Session identifier for both persisted messages.
        """
        user_msg = Message(
            role="user",
            content=user_message,
            channel=channel,
            sender_id=sender_id,
            session_id=session_id,
        )
        assistant_msg = Message(
            role="assistant",
            content=assistant_reply,
            channel=channel,
            sender_id="assistant",
            session_id=session_id,
        )
        if hasattr(self._storage, "append_messages"):
            await self._storage.append_messages([user_msg, assistant_msg])
        else:
            await self._storage.append_message(user_msg)
            await self._storage.append_message(assistant_msg)
