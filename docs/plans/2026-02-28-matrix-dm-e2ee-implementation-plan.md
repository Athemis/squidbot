# Matrix DM E2EE Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make encrypted Matrix DMs observable and processable by enabling persistent E2EE support in `MatrixChannel`, and auto-join owner invitations for both DMs and groups.

**Architecture:** Keep the existing channel interface and event pipeline. Add E2EE-aware `AsyncClient` initialization with persistent store under `~/.squidbot/crypto`, add owner-only invite auto-join handling, wire owner aliases from gateway into MatrixChannel, then add explicit encrypted-event diagnostics and dependency-failure handling.

**Tech Stack:** Python 3.14, matrix-nio, pytest, ruff, mypy, loguru.

---

## Task 1: Add failing tests for E2EE startup wiring

**Files:**
- Modify: `tests/adapters/channels/test_matrix.py`
- Modify: `tests/adapters/test_channel_loops.py`
- Modify: `tests/adapters/test_gateway_run_gateway.py`
- Modify later: `squidbot/adapters/channels/matrix.py`
- Modify later: `squidbot/cli/gateway.py`

**Step 0: Add runtime preflight for E2EE dependencies**

Run:
- `uv run python -c "import nio; print(hasattr(nio, 'AsyncClientConfig'))"`

Expected: `True` in environments that should support encrypted DMs. If false or import fails,
implementation continues with degraded-mode behavior and explicit warning logs.

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

Add a second test for encrypted event handling when E2EE is unavailable to verify error-level
logging with room/event context.

Add two startup-readiness log tests for AC5:
- E2EE available -> startup log includes readiness mode `enabled` and joined-room count.
- E2EE degraded -> startup log includes readiness mode `degraded`, reason, and joined-room count.

Add one failing permissions test:
- crypto-store directory creation applies owner-only permissions (`0700`) when creating the path.

**Step 4: Run tests to verify failure**

Run: `uv run pytest tests/adapters/channels/test_matrix.py::test_logs_encrypted_unknown_event_details -v`
Expected: FAIL before implementation.

**Step 5: Write failing tests for owner-only invite auto-join**

Add tests for invite membership events:
- owner inviter in DM -> `client.join(room_id)` is awaited
- owner inviter in group -> `client.join(room_id)` is awaited
- non-owner inviter -> join is not called
- event for different `state_key` (not bot user) -> join is not called
- join error response -> error log emitted

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

**Step 7: Write failing gateway wiring test for owner aliases**

Add a test in `tests/adapters/test_gateway_run_gateway.py` asserting owner aliases where channel is
`None` or `"matrix"` are passed to `MatrixChannel(owner_matrix_ids=...)`.

**Step 8: Run tests to verify failure**

Run: `uv run pytest tests/adapters/test_gateway_run_gateway.py -v`
Expected: FAIL before implementation.

**Step 9: Write failing encrypted inbound acceptance-path test (AC1)**

Add a test in `tests/adapters/channels/test_matrix.py` proving encrypted inbound text reaches the
normal inbound queue/receive flow once E2EE is available.

**Step 10: Run tests to verify failure**

Run: `uv run pytest tests/adapters/channels/test_matrix.py::TestMatrixChannelE2ee -v`
Expected: FAIL before implementation.

**Step 11: Write failing gateway boundary test for AC1 traceability**

Add a test in `tests/adapters/test_channel_loops.py` that simulates a decrypted encrypted inbound
message from channel receive and asserts `_channel_loop_with_state(...)` invokes
`AgentLoop.run(...)` with expected `session` and `metadata`.

**Step 12: Run tests to verify failure**

Run: `uv run pytest tests/adapters/test_channel_loops.py -v`
Expected: FAIL before implementation.

## Task 2: Implement E2EE client initialization and encrypted-event observability

**Files:**
- Modify: `squidbot/adapters/channels/matrix.py`
- Modify: `squidbot/cli/gateway.py`
- Test: `tests/adapters/channels/test_matrix.py`
- Test: `tests/adapters/test_gateway_run_gateway.py`

**Step 1: Add crypto-store path builder helper**

Implement a helper that derives and creates:
- `~/.squidbot/crypto/matrix/<sanitized-user-id>`

Use a stable sanitizer (replace non-alnum with `_`) to avoid filesystem edge cases.
When creating directories, explicitly enforce owner-only mode (`0o700`) and keep a degraded-mode
path with warning logging if permission hardening fails.

**Step 2: Build AsyncClient with E2EE config**

In `_connect()`:
- Create `nio.AsyncClientConfig(encryption_enabled=True, store_sync_tokens=True)`
- Pass config + store path to `nio.AsyncClient(...)`
- Keep existing token/user/device assignment behavior

**Step 3: Add graceful fallback for missing E2EE dependencies**

If enabling encryption raises an import/runtime warning, log actionable warning and fall back to
non-E2EE client setup so unencrypted rooms still work.

When encrypted rooms/events are encountered in degraded mode, emit error-level logs with room/event
context (no secrets).

Implement deterministic readiness detection and runtime state:
- set an explicit `self._e2ee_available` flag in `_connect()`
- set `self._e2ee_degraded_reason` (short text) when degraded
- emit startup readiness log in `_sync_loop()` with mode/reason/joined-room count

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

Run: `uv run pytest tests/adapters/channels/test_matrix.py tests/adapters/test_gateway_run_gateway.py -v`
Expected: PASS including new E2EE tests.

**Step 7: Run acceptance-focused targeted checks**

Run:
- `uv run pytest tests/adapters/channels/test_matrix.py::TestMatrixChannelE2ee -v`
- `uv run pytest tests/adapters/channels/test_matrix.py::TestMatrixChannelInvites -v`
- `uv run pytest tests/adapters/test_channel_loops.py -v`
- `uv run pytest tests/adapters/test_gateway_run_gateway.py -v`

Expected: PASS; AC1-AC5 traceability covered.

## Task 3: Validate end-to-end quality gates

**Files:**
- Verify: `squidbot/adapters/channels/matrix.py`
- Verify: `squidbot/cli/gateway.py`
- Verify: `tests/adapters/channels/test_matrix.py`
- Verify: `tests/adapters/test_gateway_run_gateway.py`

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

**Step 5: Commit implementation**

```bash
git add squidbot/adapters/channels/matrix.py squidbot/cli/gateway.py tests/adapters/channels/test_matrix.py tests/adapters/test_channel_loops.py tests/adapters/test_gateway_run_gateway.py
git commit -m "feat(matrix): add e2ee dm support and owner-only autojoin"
```

**Step 6: Push branch**

```bash
git push
```

**Step 7: Postflight readiness check (AC1 operational gate)**

Run a manual runtime smoke test in a known encrypted room and confirm startup/readiness logs report
`enabled` mode in environments that should process encrypted DMs.
