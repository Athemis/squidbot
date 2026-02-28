# Matrix DM E2EE Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make encrypted Matrix DMs observable and processable by enabling persistent E2EE support in `MatrixChannel`, and auto-join invitations only from owner identities.

**Architecture:** Keep the existing channel interface and event pipeline. Add E2EE-aware `AsyncClient` initialization with persistent store under `~/.squidbot/crypto`, add owner-only invite auto-join handling, then add explicit encrypted-event diagnostics and dependency-failure handling.

**Tech Stack:** Python 3.14, matrix-nio, pytest, ruff, mypy, loguru.

---

## Task 1: Add failing tests for E2EE startup wiring

**Files:**
- Modify: `tests/adapters/channels/test_matrix.py`
- Modify later: `squidbot/adapters/channels/matrix.py`

**Step 1: Write the failing test for persistent crypto store path**

Add a test that patches `nio.AsyncClient` and asserts `_connect()` passes:
- `store_path` under `~/.squidbot/crypto/matrix/...`
- config with encryption enabled and sync-token persistence

```python
@pytest.mark.asyncio
async def test_connect_enables_e2ee_with_persistent_store_path() -> None:
    from squidbot.adapters.channels.matrix import MatrixChannel

    cfg = _make_config(user_id="@bot:example.org")
    ch = MatrixChannel(config=cfg)

    fake_client = MagicMock()
    fake_client.add_event_callback = MagicMock()

    with patch("squidbot.adapters.channels.matrix.nio.AsyncClient", return_value=fake_client) as ctor:
        await ch._connect()

    kwargs = ctor.call_args.kwargs
    assert "/.squidbot/crypto/matrix/" in kwargs["store_path"]
    assert kwargs["config"].encryption_enabled is True
    assert kwargs["config"].store_sync_tokens is True
```

**Step 2: Run test to verify failure**

Run: `uv run pytest tests/adapters/channels/test_matrix.py::test_connect_enables_e2ee_with_persistent_store_path -v`
Expected: FAIL (current code has no explicit E2EE config/store path).

**Step 3: Write failing test for encrypted-event diagnostics**

Add a test for unknown encrypted events (`m.room.encrypted`) to verify a debug/warning log entry
contains event type, room, and sender.

**Step 4: Run tests to verify failure**

Run: `uv run pytest tests/adapters/channels/test_matrix.py::test_logs_encrypted_unknown_event_details -v`
Expected: FAIL before implementation.

**Step 5: Write failing tests for owner-only invite auto-join**

Add tests for invite membership events:
- owner inviter -> `client.join(room_id)` is awaited
- non-owner inviter -> join is not called

Example shape:

```python
@pytest.mark.asyncio
async def test_invite_from_owner_triggers_join() -> None:
    config = _make_config()
    ch = MatrixChannel(config=config, owner_matrix_ids={"@owner:example.org"})
    ch._client = MagicMock()
    ch._client.join = AsyncMock(return_value=MagicMock())

    event = MagicMock()
    event.membership = "invite"
    event.state_key = config.user_id
    event.sender = "@owner:example.org"

    room = MagicMock()
    room.room_id = "!dm:example.org"

    await ch._handle_invite(room, event)
    ch._client.join.assert_awaited_once_with("!dm:example.org")
```

**Step 6: Run tests to verify failure**

Run: `uv run pytest tests/adapters/channels/test_matrix.py::TestMatrixChannelInvites -v`
Expected: FAIL before implementation.

## Task 2: Implement E2EE client initialization and encrypted-event observability

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Test: `tests/adapters/channels/test_matrix.py`

**Step 1: Add crypto-store path builder helper**

Implement a helper that derives and creates:
- `~/.squidbot/crypto/matrix/<sanitized-user-id>`

Use a stable sanitizer (replace non-alnum with `_`) to avoid filesystem edge cases.

**Step 2: Build AsyncClient with E2EE config**

In `_connect()`:
- Create `nio.AsyncClientConfig(encryption_enabled=True, store_sync_tokens=True)`
- Pass config + store path to `nio.AsyncClient(...)`
- Keep existing token/user/device assignment behavior

**Step 3: Add graceful fallback for missing E2EE dependencies**

If enabling encryption raises an import/runtime warning, log actionable warning and fall back to
non-E2EE client setup so unencrypted rooms still work.

**Step 4: Add encrypted event diagnostics**

Enhance unknown-event handler to detect `m.room.encrypted` and log:
- room id
- sender id
- event id
- event type / algorithm (if present)

Do not include secrets.

**Step 5: Add owner-only invite auto-join path**

In `MatrixChannel`:
- accept `owner_matrix_ids: set[str] | None` in constructor
- register callback for `nio.InviteMemberEvent`
- in handler, join only when:
  - membership is `invite`
  - `state_key` equals configured bot user id
  - sender is in owner id allowlist

In gateway wiring (`_run_gateway`), derive owner matrix IDs from `settings.owner.aliases` where
channel is `None` or `"matrix"`, and pass into `MatrixChannel`.

**Step 6: Run targeted tests**

Run: `uv run pytest tests/adapters/channels/test_matrix.py -v`
Expected: PASS including new E2EE tests.

**Step 7: Commit implementation**

```bash
git add squidbot/adapters/channels/matrix.py tests/adapters/channels/test_matrix.py
git commit -m "feat(matrix): add e2ee dm support and owner-only autojoin"
```

## Task 3: Validate end-to-end quality gates

**Files:**
- Verify: `squidbot/adapters/channels/matrix.py`
- Verify: `tests/adapters/channels/test_matrix.py`

**Step 1: Run lint**

Run: `uv run ruff check .`
Expected: PASS.

**Step 2: Run format check**

Run: `uv run ruff format . --check`
Expected: PASS.

**Step 3: Run full test suite**

Run: `uv run pytest`
Expected: PASS.

**Step 4: Run type checks**

Run: `uv run mypy squidbot/`
Expected: PASS.

**Step 5: Push branch**

```bash
git push
```
