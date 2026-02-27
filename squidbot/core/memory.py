"""
Core memory manager for squidbot.

Coordinates global cross-channel history and long-term memory (MEMORY.md).
The manager is pure domain logic — it takes a MemoryPort as dependency and
contains no I/O or external service calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from squidbot.core.models import Message
from squidbot.core.ports import MemoryPort, SkillsPort

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
            reasoning_content=msg.reasoning_content,
            timestamp=msg.timestamp,
            channel=msg.channel,
            sender_id=msg.sender_id,
        )

    async def build_messages(
        self,
        user_message: str,
        system_prompt: str,
    ) -> list[Message]:
        """
        Construct the full message list for an LLM call.

        Layout: [system_prompt + memory + skills]
                + [labelled_history] + [user_message]

        Args:
            user_message: The current user input.
            system_prompt: The base system prompt (AGENTS.md content).

        Returns:
            Ordered list of messages ready to send to the LLM.
        """
        history = await self._storage.load_history(last_n=self._history_context_messages)
        global_memory = await self._storage.load_global_memory()

        # Label each history message with channel/sender context
        labelled_history = [self._label_message(msg) for msg in history]

        # Build system prompt with global memory appended
        full_system = system_prompt
        if global_memory.strip():
            full_system += f"\n\n## Your Memory\n\n{global_memory}"

        # Inject skills: XML index + full bodies of always-skills
        if self._skills is not None:
            from squidbot.core.skills import build_skills_xml  # noqa: PLC0415

            skill_list = self._skills.list_skills()
            full_system += f"\n\n{build_skills_xml(skill_list)}"
            for skill in skill_list:
                if skill.always and skill.available:
                    body = self._skills.load_skill_body(skill.name)
                    full_system += f"\n\n{body}"

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
