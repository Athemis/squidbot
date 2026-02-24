# Design: Global Cross-Channel History

**Date:** 2026-02-24  
**Status:** Approved  
**Issue:** https://github.com/Athemis/squidbot/issues/1

## Problem

The assistant serves a single user across multiple channels (CLI, Matrix, e-mail). The user may also add the assistant to group chats with other participants. The assistant must be able to recall knowledge from all channels in any other channel.

The current memory system uses per-session JSONL files, where a session is scoped to `channel:sender_id`. Session summaries are also per-session. This means knowledge from one channel is invisible in another unless the agent explicitly writes it to `MEMORY.md`.

## Solution: Approach A — Global JSONL with Temporal Context

Replace per-session JSONL files with a single global `history.jsonl` covering all channels. Each entry stores the existing message fields plus `channel` and `sender_id`. The LLM context receives the last N messages sorted by time, each labelled with `[channel / sender]`. Consolidation runs globally, producing a single cross-channel summary.

## Data Model

### Storage Layout

```
~/.squidbot/
├── history.jsonl          # all channels, append-only, sorted by time
├── history.meta.json      # global consolidation cursor
├── memory/
│   └── summary.md         # single global consolidation summary
└── workspace/
    └── MEMORY.md          # unchanged
```

Per-session files (`sessions/*.jsonl`, `sessions/*.meta.json`, `memory/<session>/summary.md`) are removed. **Migration: clean break** — existing data is not migrated.

### JSONL Entry Format

Two new fields added to the existing message format:

```json
{
  "role": "user",
  "content": "Did you see the new release?",
  "timestamp": "2026-02-24T10:00:00Z",
  "channel": "matrix",
  "sender_id": "@alice:matrix.org"
}
```

Both `channel` and `sender_id` are required on all entries, including `role: assistant` entries (where `sender_id` is always the assistant).

### Owner Configuration

New optional section in `squidbot.yaml`:

```yaml
owner:
  aliases:
    - alex                          # matches on all channels
    - address: alex@example.com
      channel: email                # scoped to e-mail only
    - address: "@alex:matrix.org"
      channel: matrix               # scoped to Matrix only
```

Unqualified strings match on all channels (fallback). Qualified entries (`{address, channel}`) are scoped to a specific channel. Channel-scoped aliases take precedence, reducing the risk of cross-channel misidentification.

## Context Injection

`MemoryManager.build_messages()` loads the last N entries from `history.jsonl` (all channels, sorted by time). Each message is prefixed with a label:

```
[matrix / @alice:matrix.org] Did you see the new release?
[matrix / owner] Not yet.
[email / owner] Send me a quick summary.
[cli / owner] What was that release again?
```

Owner messages are identified via the `aliases` config and labelled uniformly as `owner` regardless of channel.

The system prompt layout is otherwise unchanged:

```
system: [soul/identity/config] + [## Your Memory\n<MEMORY.md>] + [<skills>]
<labelled history messages>
user: <current input>
```

## Consolidation

Under the manual-only memory model, summary injection is not implemented: global recall relies on `MEMORY.md` for curated facts and on explicit `search_history` lookups when details fall outside the most recent N injected history messages.

## search_history Tool

Simplified: no multi-file scan needed. Searches `history.jsonl` directly. Matches are returned with `[channel / sender_id]` labels and timestamps.

## Affected Components

| Component | Change |
|---|---|
| `core/models.py` | `Message` gets optional `channel: str \| None` and `sender_id: str \| None` |
| `core/ports.py` | `MemoryPort` — remove `session_id` from history access signatures |
| `core/memory.py` | `MemoryManager` — remove session scope from history; `build_messages()` loads globally and labels owner messages |
| `adapters/persistence/jsonl.py` | `JsonlMemory` — single `history.jsonl` instead of N session files; cursor in `history.meta.json` |
| `adapters/tools/search_history.py` | Simplify — no multi-file scan |
| `config/schema.py` | New `owner` field with `aliases` list (strings or `{address, channel}` objects) |
| `cli/main.py` | `_make_agent_loop()` — do not pass session ID to memory |
| `AGENTS.md` | Update architecture section to reflect global history |
| `README.md` | Update memory/configuration documentation |
| `cli/onboarding.py` (or equivalent) | Extend onboarding to prompt for owner aliases |

### Unchanged

- `MEMORY.md` and `MemoryWriteTool`
- Consolidation algorithm (scope only changes)
- `AgentLoop`
- Channel adapters (`CliChannel`, `RichCliChannel`, etc.)

## Group Chats Without the Owner

In group chats, the assistant may receive messages from third parties regardless of whether the owner is present. This is already handled by the existing `group_policy` (`open`, `mention`, `allowlist`) and `allowlist` config options on Matrix and e-mail channels. Only messages that pass the policy filter reach `AgentLoop` and are written to history. No changes needed here.

## Onboarding

The interactive onboarding flow (first-run setup) must be extended to ask the user for their owner aliases. At minimum: name/nickname and any known addresses per channel. The collected values are written to the `owner.aliases` section in `squidbot.yaml`.

## Session Model

`Session` currently serves two roles: it determines which history is loaded (scope), and it carries routing information (channel + sender ID so the response can be delivered). With global history, the scoping role is removed.

Going forward:

- **Session = routing context** — short-lived, per-message, tells the channel adapter where to send the response.
- **History = global memory** — long-lived, cross-channel, independent of session.

`AgentLoop` continues to pass `Session` to channel adapters for routing. `MemoryManager` ignores session identity when loading or writing history.

## Concurrency

Multiple AgentLoop instances may write to `history.jsonl` simultaneously when the user is active on several channels in parallel. Use `fcntl.flock` for file-level write locking — simple, no new dependencies, sufficient for the single-user case.

> **TODO:** Revisit if async write contention becomes a practical problem (e.g. replace with an asyncio write queue).

## Open Issues

- [#2](https://github.com/Athemis/squidbot/issues/2) — Consider token-based instead of message-count-based context window cutoff once high-volume channels (e-mail) are integrated.
