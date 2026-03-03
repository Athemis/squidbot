# Message Tool Routing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `send_attachment` with a dedicated `message` tool and move to native list attachments in `OutboundMessage`, with owner+explicit routed sends and unchanged default AgentLoop reply behavior.

**Architecture:** First change the domain attachment model to `attachments: list[Path]`, then adapt channels and tests to that native shape. After the model is stable, introduce `MessageTool` with policy/routing checks and inject it in gateway loops. `send_attachment` is removed directly in this work (no compatibility phase), then prompt guidance is updated.

**Tech Stack:** Python 3.14, asyncio, pytest, mypy --strict, ruff, dataclasses, existing channel adapters.

---

### Task 1: Add failing model tests for native list attachments

**Files:**
- Modify: `tests/core/test_models.py`

**Step 1: Write failing tests for new `OutboundMessage.attachments` contract**

```python
def test_outbound_message_attachments_default_empty_list() -> None:
    msg = OutboundMessage(session=Session(channel="matrix", sender_id="u"), text="hi")
    assert msg.attachments == []


def test_outbound_message_attachments_accepts_list() -> None:
    p = Path("/tmp/x.txt")
    msg = OutboundMessage(
        session=Session(channel="matrix", sender_id="u"),
        text="hi",
        attachments=[p],
    )
    assert msg.attachments == [p]
```

**Step 2: Run targeted tests to verify fail**

Run: `uv run pytest tests/core/test_models.py -k "attachments_default_empty_list or attachments_accepts_list" -v`
Expected: FAIL while model still uses singular `attachment`.

**Step 3: Commit**

```bash
git add tests/core/test_models.py
git commit -m "test: add failing native attachment list model tests"
```

### Task 2: Migrate domain model to native attachment list

**Files:**
- Modify: `squidbot/core/models.py`
- Modify: `tests/core/test_models.py`

**Step 1: Implement minimal model change**

```python
@dataclass
class OutboundMessage:
    session: Session
    text: str
    attachments: list[Path] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

**Step 2: Run targeted model tests**

Run: `uv run pytest tests/core/test_models.py -v`
Expected: PASS for updated model behavior.

**Step 3: Commit**

```bash
git add squidbot/core/models.py tests/core/test_models.py
git commit -m "feat(core): migrate outbound message to native attachment list"
```

### Task 3: Adapt channel adapters to native attachment list

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `squidbot/adapters/channels/email.py`
- Modify: `squidbot/adapters/channels/cli.py` (if signature assumptions need updates)
- Modify: `tests/adapters/channels/test_matrix.py`
- Modify: `tests/adapters/channels/test_email.py`

**Step 1: Write failing Matrix/Email tests for list behavior**

```python
async def test_matrix_send_uploads_all_attachments_before_text(...): ...
async def test_email_send_attaches_all_files(...): ...
```

**Step 2: Run channel subset to verify fail**

Run: `uv run pytest tests/adapters/channels/test_matrix.py tests/adapters/channels/test_email.py -k "attachments" -v`
Expected: FAIL while adapters still read singular field.

**Step 3: Implement minimal adapter migration**

- Matrix: iterate `for path in message.attachments` and preserve current ordering semantics.
- Email: attach each existing file from `message.attachments`.
- CLI channels: continue ignoring attachments.

**Step 4: Re-run channel subset**

Run: `uv run pytest tests/adapters/channels/test_matrix.py tests/adapters/channels/test_email.py -k "attachments" -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/adapters/channels/matrix.py squidbot/adapters/channels/email.py squidbot/adapters/channels/cli.py tests/adapters/channels/test_matrix.py tests/adapters/channels/test_email.py
git commit -m "feat(channels): support native outbound attachment lists"
```

### Task 4: Add failing tests for new MessageTool contract and routing policy

**Files:**
- Create: `tests/adapters/tools/test_message.py`

**Step 1: Write failing contract tests**

```python
def test_message_tool_definition_exposes_attachments_list() -> None:
    assert "attachments" in tool.parameters["properties"]
```

**Step 2: Write failing behavior tests**

```python
async def test_message_tool_sends_current_context_with_attachments(...): ...
async def test_non_owner_routed_send_denied_even_if_explicit(...): ...
async def test_owner_routed_send_denied_when_not_explicit(...): ...
async def test_non_owner_target_sender_override_denied(...): ...
async def test_owner_target_sender_override_denied_without_explicit(...): ...
async def test_same_channel_target_sender_override_denied_v1(...): ...
async def test_matrix_to_email_allowed_for_owner_explicit(...): ...
async def test_email_to_matrix_unsupported_v1(...): ...
async def test_unknown_target_channel_denied(...): ...
async def test_unresolved_target_sender_returns_deterministic_error(...): ...
async def test_ambiguous_target_sender_returns_deterministic_error(...): ...
async def test_unresolvable_target_state_returns_deterministic_error(...): ...
async def test_mixed_valid_invalid_attachments_fails_atomically(...): ...
```

**Step 3: Run new test file to verify fail**

Run: `uv run pytest tests/adapters/tools/test_message.py -v`
Expected: FAIL because `MessageTool` is not implemented.

**Step 4: Commit**

```bash
git add tests/adapters/tools/test_message.py
git commit -m "test: add failing message tool routing and policy coverage"
```

### Task 5: Implement MessageTool and remove SendAttachmentTool

**Files:**
- Create: `squidbot/adapters/tools/message.py`
- Modify: `squidbot/adapters/tools/files.py`
- Modify: `tests/adapters/tools/test_message.py`

**Step 1: Implement minimal `MessageTool` structure**

```python
class MessageTool:
    name = "message"
    parameters = {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "attachments": {"type": "array", "items": {"type": "string"}},
            "target_channel": {"type": "string"},
            "target_sender_id": {"type": "string"},
        },
        "required": ["content"],
    }
```

**Step 2: Implement owner resolver and explicitness helper**

```python
def _is_owner_sender(sender_id: str, channel: str, aliases: list[OwnerAliasEntry]) -> bool: ...
def _is_explicit_routing_request(text: str, target_channel: str, target_sender_id: str) -> bool: ...
```

**Step 3: Implement route capability checks**

```python
def _is_supported_route(source_channel: str, target_channel: str, sender_override: bool) -> bool:
    # v1: same-channel no sender override, matrix->email supported, email->matrix denied
```

**Step 3b: Implement deterministic target resolution and error mapping**

Define explicit resolution precedence and deterministic errors:

- provided `target_sender_id` wins
- fallback recipient candidates from channel-scoped email aliases first, then unscoped email-like aliases
- fallback recipient only if exactly one candidate resolves
- ambiguous/unresolved recipient -> deterministic error
- unknown channel vs unsupported route vs unresolved recipient use different error strings

**Step 4: Implement execute path**

- validate content
- resolve route target
- enforce owner+explicit for any override
- resolve attachment paths safely
- validate full attachment batch before sending (all-or-nothing)
- build one `OutboundMessage` with native `attachments` list
- dispatch via route callback
- emit structured allow/deny audit log with reason code (no sensitive message body)
- return value errors on failures

**Step 5: Remove `SendAttachmentTool` from filesystem module**

Delete the class and keep file tools focused on file IO.

**Step 6: Run message tool tests**

Run: `uv run pytest tests/adapters/tools/test_message.py -v`
Expected: PASS.

**Step 7: Commit**

```bash
git add squidbot/adapters/tools/message.py squidbot/adapters/tools/files.py tests/adapters/tools/test_message.py
git commit -m "feat: add message tool with owner-explicit routed delivery policy"
```

### Task 6: Wire MessageTool into gateway loops

**Files:**
- Modify: `squidbot/cli/gateway.py`
- Modify: `tests/adapters/test_channel_loops.py`
- Modify: `tests/adapters/test_gateway_status.py`

**Step 1: Write failing wiring assertions**

```python
assert any(getattr(t, "name", None) == "message" for t in kwargs["extra_tools"])
assert not any(getattr(t, "name", None) == "send_attachment" for t in kwargs["extra_tools"])
```

**Step 2: Run loop tests to verify fail**

Run: `uv run pytest tests/adapters/test_channel_loops.py -v`
Expected: FAIL.

**Step 3: Implement wiring**

- inject `MessageTool` in `_channel_loop` and `_channel_loop_with_state`
- pass owner aliases, inbound text, session context, metadata, workspace restriction context
- pass target routing callback bound to active channel registry

**Step 4: Re-run loop/status subset**

Run: `uv run pytest tests/adapters/test_channel_loops.py tests/adapters/test_gateway_status.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/cli/gateway.py tests/adapters/test_channel_loops.py tests/adapters/test_gateway_status.py
git commit -m "feat(gateway): inject message tool with routing context"
```

### Task 7: Delete send_attachment code/test leftovers

**Files:**
- Delete: `tests/adapters/tools/test_send_attachment.py`
- Modify: `tests/adapters/tools/test_message.py`

**Step 1: Verify `message` coverage passes before deletion**

Run: `uv run pytest tests/adapters/tools/test_message.py -v`
Expected: PASS.

**Step 2: Delete legacy test file**

Remove `tests/adapters/tools/test_send_attachment.py`.

**Step 3: Verify no `SendAttachmentTool` symbol references remain**

Run: `rg "SendAttachmentTool" squidbot tests`
Expected: no matches.

**Step 4: Commit**

```bash
git add tests/adapters/tools/test_message.py tests/adapters/tools/test_send_attachment.py
git commit -m "test: remove legacy send_attachment coverage after message tool cutover"
```

### Task 8: Update prompt guidance for message tool usage

**Files:**
- Modify: `squidbot/cli/gateway.py`
- Modify: `squidbot/workspace/AGENTS.md`
- Modify: `tests/adapters/test_spawn_wiring.py`

**Step 1: Write failing guidance test**

```python
assert "message" in loop._system_prompt
assert "attachments" in loop._system_prompt
assert "send_attachment" not in loop._system_prompt
```

**Step 2: Run targeted guidance test**

Run: `uv run pytest tests/adapters/test_spawn_wiring.py::test_attachment_guidance_mentions_message_tool -v`
Expected: FAIL.

**Step 3: Update guidance text**

Guidance: create file(s) with `write_file`, deliver using `message` and `attachments`.

**Step 4: Re-run spawn wiring tests**

Run: `uv run pytest tests/adapters/test_spawn_wiring.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/cli/gateway.py squidbot/workspace/AGENTS.md tests/adapters/test_spawn_wiring.py
git commit -m "docs(prompt): guide attachment delivery via message tool"
```

### Task 9: Full verification

**Files:**
- Modify (if needed): `docs/plans/2026-03-01-message-tool-routing-design.md`
- Modify (if needed): `docs/plans/2026-03-01-message-tool-routing-implementation-plan.md`

**Step 1: Run lint**

Run: `uv run ruff check .`
Expected: PASS.

**Step 2: Run format check**

Run: `uv run ruff format . --check`
Expected: PASS.

**Step 3: Run typing**

Run: `uv run mypy squidbot/`
Expected: PASS.

**Step 4: Run full tests**

Run: `uv run pytest`
Expected: PASS.

**Step 5: Verify model migration references**

Run: `rg "message\.attachment|attachment=" squidbot tests`
Expected: no matches in production/test code except historical docs/plans.

Run: `rg "send_attachment" squidbot tests`
Expected: no matches after Task 8 prompt migration.

**Step 6: Final commit**

```bash
git add squidbot/core/models.py squidbot/adapters/tools/message.py squidbot/adapters/tools/files.py squidbot/adapters/channels/matrix.py squidbot/adapters/channels/email.py squidbot/cli/gateway.py squidbot/workspace/AGENTS.md tests/core/test_models.py tests/adapters/tools/test_message.py tests/adapters/channels/test_matrix.py tests/adapters/channels/test_email.py tests/adapters/test_channel_loops.py tests/adapters/test_gateway_status.py tests/adapters/test_spawn_wiring.py docs/plans/2026-03-01-message-tool-routing-design.md docs/plans/2026-03-01-message-tool-routing-implementation-plan.md
git commit -m "feat: add dedicated message tool with native attachment list routing"
```

**Step 7: Prepare PR summary**

```text
## Summary
- migrate outbound messages to native attachment lists
- add dedicated message tool with owner+explicit routing policy
- remove send_attachment tool and legacy tests
- update gateway wiring, channels, and prompt guidance
```
