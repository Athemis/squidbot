# Search History Tool Design

**Date:** 2026-02-23
**Status:** Approved — implementation pending

## Problem

squidbot's memory is session-scoped: `memory.md` holds facts the agent writes explicitly, and the JSONL history holds the raw conversation. There is no way for the agent to search *across sessions* to answer questions like "what did we decide about X last week?" — episodic memory is missing.

## Goal

Add a `search_history` tool that enables the agent to search across all JSONL session files for past conversations, providing episodic memory without embeddings or external services.

## Non-Goals

- Semantic / vector search (substring match is sufficient for a daily driver)
- Indexing / caching (at personal-assistant scale, reading JSONL files on demand is fast enough)
- Writing to history (tool is read-only)
- Replacing `memory.md` (the two are complementary: memory.md = facts, search_history = episodes)

## Key Decisions

### Why not HISTORY.md?

HISTORY.md (nanobot-redux pattern) requires the agent to proactively and consistently write entries. In practice this is unreliable — the agent must be prompted to do it and may still skip it. The JSONL history already contains *everything* automatically. `search_history` makes existing data accessible without agent discipline.

### Substring match, not embeddings

- No embedding provider required
- No extra dependencies
- Sufficient for the use case ("did we discuss X?" where X is a keyword)
- Vector search can be added later as a separate feature

### Read JSONL directly, not via MemoryPort

`SearchHistoryTool` reads JSONL files directly from `base_dir/sessions/` using the existing `_deserialize_message()` helper. This avoids adding cross-session query methods to `MemoryPort` (which is session-scoped by design).

### Only user/assistant roles in output

Tool-call messages and tool-result messages are excluded — they are noisy and often contain raw data not useful for the agent's recall. The user and assistant turns represent the meaningful conversation.

### Context window (±1 message)

Matches are returned with the message immediately before and after, giving the agent enough context to understand what was being discussed without overwhelming the output.

## Architecture

```
SearchHistoryTool.execute(query, days?, max_results?)
    │
    ├── glob sessions/*.jsonl
    ├── for each file:
    │     deserialize messages
    │     filter by timestamp if days > 0
    ├── search user/assistant content (case-insensitive)
    ├── collect up to max_results matches
    ├── for each match: include ±1 surrounding messages
    └── format as Markdown, return as ToolResult
```

## Output Format

```
## Match 1 — Session: cli__local | 2026-02-20 14:32

USER: Was haben wir über Python Packaging besprochen?
**ASSISTANT: Wir haben uv als Package Manager gewählt...**
USER: Ok, und das Argument für PEP 517?

---
## Match 2 — ...
```

Matched message is bold. Content truncated at 300 chars per message.

## Configuration

```yaml
tools:
  search_history:
    enabled: true   # default: true
```

Simple boolean — no further config needed at this stage.

## Trade-offs Considered

| Option | Decision |
|---|---|
| HISTORY.md (agent-curated) vs. search over JSONL | Search over JSONL — no agent discipline required |
| Embeddings vs. substring match | Substring — simpler, no dependencies |
| MemoryPort cross-session API vs. direct JSONL read | Direct read — keeps MemoryPort session-scoped |
| ±1 context vs. larger window | ±1 — sufficient for recall, avoids bloating output |

## Files Changed

- `squidbot/adapters/tools/search_history.py` — new tool
- `squidbot/config/schema.py` — `SearchHistoryConfig` + field on `ToolsConfig`
- `squidbot/cli/main.py` — register tool when enabled
- `README.md` — document config option
