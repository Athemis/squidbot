# Design: Remove Unused `build_messages` Parameters

## Problem

`MemoryManager.build_messages()` declares `channel` and `sender_id` parameters that are never used in the function body. This is API smell — callers pass values that are silently ignored.

## Analysis

**Data flow:**

1. `build_messages()` reads stored messages from history (via `load_history()`)
2. Each stored `Message` already has `channel` and `sender_id` set (populated by `persist_exchange()`)
3. `_label_message()` reads these fields directly from the `Message` objects
4. The current user message is appended without metadata — it's the immediate input, not yet persisted

**Why the parameters are unused:**

- The current user message doesn't need labeling (it's the active conversation turn)
- Historical messages already carry their metadata in the `Message` objects
- `persist_exchange()` handles metadata correctly for persistence

**No downstream impact:**

- `persist_exchange()` continues to require `channel` and `sender_id` — unchanged
- All labeling tests pass because they test stored message labeling, not the current message

## Decision

Remove the unused parameters. YAGNI applies — no concrete use case exists for them.

## Scope

| File | Change |
|------|--------|
| `squidbot/core/memory.py` | Remove `channel` and `sender_id` from `build_messages()` signature |
| `squidbot/core/agent.py` | Update callsite to remove the two arguments |
| `tests/core/test_memory.py` | Update all calls to remove the two arguments |
| `tests/adapters/tools/test_spawn.py` | Update `AsyncMock` setups |

## Out of Scope

- Any changes to `persist_exchange()`
- Refactoring `_label_message()` or `_is_owner()`
- Changes to Message model

## API Change

**Before:**

```python
async def build_messages(
    self,
    channel: str,
    sender_id: str,
    user_message: str,
    system_prompt: str,
) -> list[Message]:
```

**After:**

```python
async def build_messages(
    self,
    user_message: str,
    system_prompt: str,
) -> list[Message]:
```

## Definition of Done

- [ ] `build_messages()` has only `user_message` and `system_prompt` parameters
- [ ] All callsites updated
- [ ] `uv run ruff check .` passes
- [ ] `uv run mypy squidbot/` passes
- [ ] `uv run pytest` passes
