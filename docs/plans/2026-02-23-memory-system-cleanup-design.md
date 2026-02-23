# Memory System Cleanup — Design Document

**Date:** 2026-02-23
**Status:** Partially superseded — see note on D3 below
**Scope:** Post-implementation cleanup after Features A, B, C (consolidation cursor, global memory redesign, small fixes)

---

## Problem Statement

After implementing the two-level memory model (global `MEMORY.md` + per-session `summary.md`), three gaps remain:

### Gap 1 — Agent doesn't know how to use its own memory

`squidbot/skills/memory/SKILL.md` has 10 lines and says nothing actionable:

```
Use the `memory_write` tool to update your memory document with important information
that should persist across sessions.
```

The agent receives no guidance on:
- The distinction between global MEMORY.md (agent-curated, cross-session) and session summary (auto-generated, read-only for agent)
- When to proactively call `memory_write`
- That `memory_write` replaces the full document (merge required)
- How to keep MEMORY.md compact

**Effect:** The agent will either never write to memory, or overwrite it with garbage.

### Gap 2 — `memory_write` tool description references old model

The class docstring still says `memory.md` (old lowercase name). The `description` attribute (shown to the LLM as the tool description) doesn't mention:
- That this is a **global, cross-session** document
- That content is visible under `## Your Memory` in future sessions
- The ~300-word size guidance

**Effect:** Minor, but inconsistent with the actual behaviour and confusing if the agent reads its own tool list.

### Gap 3 — Session summary grows unboundedly

`MemoryManager._consolidate()` always appends the new summary to the existing one:

```python
updated = f"{existing}\n\n{summary}" if existing.strip() else summary
```

In a very long session (many consolidation cycles), `session_summary` can accumulate thousands of words. It is injected into the system prompt on every turn, consuming a growing slice of the context window.

**Effect:** After O(10+) consolidation cycles in a single session, the session summary begins to degrade LLM performance. For a daily-driver personal assistant with long sessions this will eventually happen.

---

## Design Decisions

### D1 — SKILL.md rewrite

The skill file is the primary instruction source for the agent's memory behaviour. It should answer:

1. **What is MEMORY.md?** Global, agent-curated, cross-session. Always visible.
2. **What is Session Summary?** Auto-generated, read-only for agent. Summarises earlier turns.
3. **When to call `memory_write`?** Proactively on new persistent facts (preferences, projects, key facts). Not for ephemeral context.
4. **How to call it?** Read existing `## Your Memory`, merge new info, keep ≤ ~300 words, write clean Markdown.
5. **What NOT to do?** Don't write ephemeral context. Don't let MEMORY.md grow. Don't confuse the two levels.

The `always: false` frontmatter stays — the skill is available on demand. The agent sees it listed in the skills XML on every turn.

### D2 — `memory_write.py` description update

Two changes:
1. **Class docstring:** Replace `memory.md` with `MEMORY.md`, add note about global/cross-session, add merge-required note.
2. **`description` attribute (LLM-facing):** Add "global", "cross-session", visible under `## Your Memory`, ~300-word guidance.

No behaviour changes. No test changes.

### D3 — Session summary cap

> **⚠️ Superseded:** The paragraph-trim approach below was implemented and shipped, but the
> design decision was subsequently reconsidered. The hard-cut approach discards the oldest
> consolidation cycles entirely, which loses information that may be relevant to the current
> session. The replacement design uses **meta-consolidation** — when the summary exceeds the
> word threshold, the LLM is called to re-summarise the entire summary into a compact form,
> preserving all information at reduced size.
>
> See `docs/plans/2026-02-23-meta-consolidation-design.md` for the replacement design.

**Original approach (implemented, to be replaced):** After computing `updated` in
`_consolidate()`, apply a word-count guard. If `len(updated.split()) > 600`, keep only
the last 8 non-empty paragraphs (split on `\n\n`).

**Why this was rejected:** Hard-cutting oldest paragraphs discards information. For a
personal assistant daily driver, earlier parts of a session are still potentially relevant
(e.g. "we decided not to do X" at session start). Meta-consolidation preserves all
information in compressed form.

**Where (current implementation):** `_trim_summary(text: str) -> str` in
`squidbot/core/memory.py`, called after computing `updated` in `_consolidate()`.

**Constants (to be removed in meta-consolidation):**
```python
_SUMMARY_WORD_LIMIT = 600
_SUMMARY_KEEP_PARAGRAPHS = 8
```

**No port changes.** No new files. No changes to `JsonlMemory`.

---

## What Is NOT In Scope

- Fixing Matrix/Email channels' lack of `memory_write` — accepted gap, out of scope
- Making `search_history` search MEMORY.md — not needed (it's always in context)
- Adding a MEMORY.md size cap — the skill instructs the agent to keep it compact; a hard cap would require a separate read-before-write mechanism and is YAGNI for now
- Changing consolidation threshold or keep_recent_ratio defaults

---

## Files Changed

| File | Change |
|------|--------|
| `squidbot/skills/memory/SKILL.md` | Full rewrite |
| `squidbot/adapters/tools/memory_write.py` | Docstring + description update |
| `squidbot/core/memory.py` | Add `_SUMMARY_WORD_LIMIT`, `_SUMMARY_KEEP_PARAGRAPHS`, `_trim_summary()`, call in `_consolidate()` |
| `tests/core/test_memory.py` | Two new tests for summary cap behaviour |

No new files. No schema/port changes. No migration needed.
