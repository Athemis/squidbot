"""Tests for MessageTool routed delivery behavior."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from squidbot.config.schema import OwnerAliasEntry
from squidbot.core.models import OutboundMessage, Session

if TYPE_CHECKING:
    from squidbot.adapters.tools.message import MessageTool


class _CollectingChannel:
    """Test double that records outbound messages."""

    streaming: bool = False

    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []

    async def send(self, message: OutboundMessage) -> None:
        self.sent.append(message)

    async def send_typing(self, session_id: str, typing: bool = True) -> None:
        return


class _FailingChannel(_CollectingChannel):
    """Test double that fails during send()."""

    async def send(self, message: OutboundMessage) -> None:
        raise RuntimeError("boom")


def _owner_aliases(
    *, sender_id: str, sender_channel: str, emails: list[str]
) -> list[OwnerAliasEntry]:
    aliases = [OwnerAliasEntry(address=sender_id, channel=sender_channel)]
    aliases.extend(OwnerAliasEntry(address=email, channel="email") for email in emails)
    return aliases


def _make_tool(
    *,
    channels: dict[str, Any],
    session: Session,
    inbound_text: str,
    owner_aliases: list[OwnerAliasEntry],
    outbound_metadata: dict[str, Any],
    workspace: Path,
    restrict_to_workspace: bool = False,
    current_sender_id: str | None = None,
) -> MessageTool:
    from squidbot.adapters.tools.message import MessageTool

    return MessageTool(
        channel_registry=channels,
        current_session=session,
        inbound_text=inbound_text,
        owner_aliases=owner_aliases,
        outbound_metadata=outbound_metadata,
        workspace=workspace,
        restrict_to_workspace=restrict_to_workspace,
        current_sender_id=current_sender_id,
    )


class TestMessageToolDefinition:
    def test_message_tool_definition_exposes_attachments_list(self, tmp_path: Path) -> None:
        matrix = _CollectingChannel()
        session = Session(channel="matrix", sender_id="@owner:example.org")
        tool = _make_tool(
            channels={"matrix": matrix},
            session=session,
            inbound_text="hello",
            owner_aliases=[],
            outbound_metadata={"matrix_room_id": "!room:example.org"},
            workspace=tmp_path,
        )

        assert tool.name == "message"
        assert "content" in tool.parameters["required"]
        assert "attachments" in tool.parameters["properties"]


class TestMessageToolCurrentContext:
    async def test_sends_current_context_with_attachments(self, tmp_path: Path) -> None:
        matrix = _CollectingChannel()
        session = Session(channel="matrix", sender_id="@owner:example.org")
        path = tmp_path / "a.txt"
        path.write_text("hello", encoding="utf-8")
        tool = _make_tool(
            channels={"matrix": matrix},
            session=session,
            inbound_text="send",
            owner_aliases=[],
            outbound_metadata={"matrix_room_id": "!room:example.org"},
            workspace=tmp_path,
        )

        result = await tool.execute(content="Here", attachments=[str(path)])

        assert not result.is_error
        assert len(matrix.sent) == 1
        sent = matrix.sent[0]
        assert sent.session == session
        assert sent.text == "Here"
        assert sent.attachments == [path]

    async def test_mixed_valid_invalid_attachments_fails_atomically(self, tmp_path: Path) -> None:
        matrix = _CollectingChannel()
        session = Session(channel="matrix", sender_id="@owner:example.org")
        good = tmp_path / "ok.txt"
        bad = tmp_path / "missing.txt"
        good.write_text("ok", encoding="utf-8")
        tool = _make_tool(
            channels={"matrix": matrix},
            session=session,
            inbound_text="send",
            owner_aliases=[],
            outbound_metadata={"matrix_room_id": "!room:example.org"},
            workspace=tmp_path,
        )

        result = await tool.execute(content="Here", attachments=[str(good), str(bad)])

        assert result.is_error
        assert "does not exist" in result.content or "attachment" in result.content.lower()
        assert matrix.sent == []


class TestMessageToolRoutingPolicy:
    async def test_non_owner_routed_send_denied_even_if_explicit(self, tmp_path: Path) -> None:
        matrix = _CollectingChannel()
        email = _CollectingChannel()
        session = Session(channel="matrix", sender_id="@guest:example.org")
        tool = _make_tool(
            channels={"matrix": matrix, "email": email},
            session=session,
            inbound_text="Please send this per email.",
            owner_aliases=[],
            outbound_metadata={"matrix_room_id": "!room:example.org"},
            workspace=tmp_path,
        )

        result = await tool.execute(
            content="Denied",
            target_channel="email",
            target_sender_id="guest@example.org",
        )

        assert result.is_error
        assert "owner" in result.content.lower()
        assert email.sent == []

    async def test_owner_routed_send_denied_when_not_explicit(self, tmp_path: Path) -> None:
        matrix = _CollectingChannel()
        email = _CollectingChannel()
        sender = "@owner:example.org"
        session = Session(channel="matrix", sender_id=sender)
        tool = _make_tool(
            channels={"matrix": matrix, "email": email},
            session=session,
            inbound_text="just answering here",
            owner_aliases=_owner_aliases(sender_id=sender, sender_channel="matrix", emails=[]),
            outbound_metadata={"matrix_room_id": "!room:example.org"},
            workspace=tmp_path,
        )

        result = await tool.execute(
            content="Denied",
            target_channel="email",
            target_sender_id="owner@example.org",
        )

        assert result.is_error
        assert "explicit" in result.content.lower()
        assert email.sent == []

    async def test_non_owner_target_sender_override_denied(self, tmp_path: Path) -> None:
        matrix = _CollectingChannel()
        session = Session(channel="matrix", sender_id="@guest:example.org")
        tool = _make_tool(
            channels={"matrix": matrix},
            session=session,
            inbound_text="send to @bob in matrix",
            owner_aliases=[],
            outbound_metadata={"matrix_room_id": "!room:example.org"},
            workspace=tmp_path,
        )

        result = await tool.execute(content="No", target_sender_id="@bob:example.org")

        assert result.is_error
        assert matrix.sent == []

    async def test_owner_target_sender_override_denied_without_explicit(
        self, tmp_path: Path
    ) -> None:
        matrix = _CollectingChannel()
        sender = "@owner:example.org"
        session = Session(channel="matrix", sender_id=sender)
        tool = _make_tool(
            channels={"matrix": matrix},
            session=session,
            inbound_text="normal reply",
            owner_aliases=_owner_aliases(sender_id=sender, sender_channel="matrix", emails=[]),
            outbound_metadata={"matrix_room_id": "!room:example.org"},
            workspace=tmp_path,
        )

        result = await tool.execute(content="No", target_sender_id="@bob:example.org")

        assert result.is_error
        assert "explicit" in result.content.lower()

    async def test_same_channel_target_sender_override_denied_v1(self, tmp_path: Path) -> None:
        matrix = _CollectingChannel()
        sender = "@owner:example.org"
        session = Session(channel="matrix", sender_id=sender)
        tool = _make_tool(
            channels={"matrix": matrix},
            session=session,
            inbound_text="Please send this to @bob in matrix.",
            owner_aliases=_owner_aliases(sender_id=sender, sender_channel="matrix", emails=[]),
            outbound_metadata={"matrix_room_id": "!room:example.org"},
            workspace=tmp_path,
        )

        result = await tool.execute(content="No", target_sender_id="@bob:example.org")

        assert result.is_error
        assert "supported" in result.content.lower() or "override" in result.content.lower()


class TestMessageToolRoutingResolution:
    async def test_matrix_to_email_allowed_for_owner_explicit(self, tmp_path: Path) -> None:
        matrix = _CollectingChannel()
        email = _CollectingChannel()
        sender = "@owner:example.org"
        session = Session(channel="matrix", sender_id=sender)
        tool = _make_tool(
            channels={"matrix": matrix, "email": email},
            session=session,
            inbound_text="Please send this per email.",
            owner_aliases=_owner_aliases(sender_id=sender, sender_channel="matrix", emails=[]),
            outbound_metadata={"matrix_room_id": "!room:example.org"},
            workspace=tmp_path,
        )

        result = await tool.execute(
            content="Delivered",
            target_channel="email",
            target_sender_id="owner@example.org",
        )

        assert not result.is_error
        assert len(email.sent) == 1
        assert email.sent[0].session.channel == "email"
        assert email.sent[0].session.sender_id == "owner@example.org"

    async def test_matrix_room_session_uses_current_sender_id_for_owner_routing(
        self, tmp_path: Path
    ) -> None:
        matrix = _CollectingChannel()
        email = _CollectingChannel()
        room_session = Session(channel="matrix", sender_id="!room1:example.org")
        owner_sender = "@owner:example.org"
        tool = _make_tool(
            channels={"matrix": matrix, "email": email},
            session=room_session,
            inbound_text="Please send this per email.",
            owner_aliases=_owner_aliases(
                sender_id=owner_sender,
                sender_channel="matrix",
                emails=[],
            ),
            outbound_metadata={"matrix_room_id": "!room1:example.org"},
            workspace=tmp_path,
            current_sender_id=owner_sender,
        )

        result = await tool.execute(
            content="Delivered",
            target_channel="email",
            target_sender_id="owner@example.org",
        )

        assert not result.is_error
        assert len(email.sent) == 1

    async def test_email_to_matrix_unsupported_v1(self, tmp_path: Path) -> None:
        matrix = _CollectingChannel()
        email = _CollectingChannel()
        sender = "owner@example.org"
        session = Session(channel="email", sender_id=sender)
        tool = _make_tool(
            channels={"matrix": matrix, "email": email},
            session=session,
            inbound_text="Send this to matrix please.",
            owner_aliases=_owner_aliases(sender_id=sender, sender_channel="email", emails=[]),
            outbound_metadata={"email_from": sender},
            workspace=tmp_path,
        )

        result = await tool.execute(
            content="Denied",
            target_channel="matrix",
            target_sender_id="@owner:example.org",
        )

        assert result.is_error
        assert "not supported" in result.content.lower()

    async def test_unknown_target_channel_denied(self, tmp_path: Path) -> None:
        matrix = _CollectingChannel()
        sender = "@owner:example.org"
        session = Session(channel="matrix", sender_id=sender)
        tool = _make_tool(
            channels={"matrix": matrix},
            session=session,
            inbound_text="send this per email",
            owner_aliases=_owner_aliases(sender_id=sender, sender_channel="matrix", emails=[]),
            outbound_metadata={"matrix_room_id": "!room:example.org"},
            workspace=tmp_path,
        )

        result = await tool.execute(content="Nope", target_channel="email")

        assert result.is_error
        assert "unavailable" in result.content.lower() or "unknown" in result.content.lower()

    async def test_unresolved_target_sender_returns_deterministic_error(
        self, tmp_path: Path
    ) -> None:
        matrix = _CollectingChannel()
        email = _CollectingChannel()
        sender = "@owner:example.org"
        session = Session(channel="matrix", sender_id=sender)
        tool = _make_tool(
            channels={"matrix": matrix, "email": email},
            session=session,
            inbound_text="send this per email",
            owner_aliases=_owner_aliases(sender_id=sender, sender_channel="matrix", emails=[]),
            outbound_metadata={"matrix_room_id": "!room:example.org"},
            workspace=tmp_path,
        )

        result = await tool.execute(content="No target", target_channel="email")

        assert result.is_error
        assert "could not be resolved" in result.content.lower()

    async def test_ambiguous_target_sender_returns_deterministic_error(
        self, tmp_path: Path
    ) -> None:
        matrix = _CollectingChannel()
        email = _CollectingChannel()
        sender = "@owner:example.org"
        session = Session(channel="matrix", sender_id=sender)
        tool = _make_tool(
            channels={"matrix": matrix, "email": email},
            session=session,
            inbound_text="send this per email",
            owner_aliases=_owner_aliases(
                sender_id=sender,
                sender_channel="matrix",
                emails=["first@example.org", "second@example.org"],
            ),
            outbound_metadata={"matrix_room_id": "!room:example.org"},
            workspace=tmp_path,
        )

        result = await tool.execute(content="No target", target_channel="email")

        assert result.is_error
        assert "could not be resolved" in result.content.lower()

    async def test_unresolvable_target_state_returns_deterministic_error(
        self, tmp_path: Path
    ) -> None:
        matrix = _CollectingChannel()
        sender = "@owner:example.org"
        session = Session(channel="matrix", sender_id=sender)
        tool = _make_tool(
            channels={"matrix": matrix},
            session=session,
            inbound_text="send in this room",
            owner_aliases=_owner_aliases(sender_id=sender, sender_channel="matrix", emails=[]),
            outbound_metadata={},
            workspace=tmp_path,
        )

        result = await tool.execute(content="No room metadata")

        assert result.is_error
        assert "could not be resolved" in result.content.lower()

    async def test_channel_send_failure_returns_error(self, tmp_path: Path) -> None:
        matrix = _FailingChannel()
        sender = "@owner:example.org"
        session = Session(channel="matrix", sender_id=sender)
        tool = _make_tool(
            channels={"matrix": matrix},
            session=session,
            inbound_text="send",
            owner_aliases=_owner_aliases(sender_id=sender, sender_channel="matrix", emails=[]),
            outbound_metadata={"matrix_room_id": "!room:example.org"},
            workspace=tmp_path,
        )

        result = await tool.execute(content="Boom")

        assert result.is_error
        assert "failed" in result.content.lower() or "error" in result.content.lower()
