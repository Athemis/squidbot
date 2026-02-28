---
name: memory
description: "Manages long-term cross-session memory in `MEMORY.md`. Use when durable user preferences, facts, or ongoing context should persist across sessions."
always: true
requires: {}
---

# Memory

## When to Use

- The user shares durable preferences or profile facts worth retaining.
- A long-running project needs continuity across sessions or channels.
- The user explicitly asks to remember something for later.

**`## Your Memory`** — Your global cross-session notes (MEMORY.md). Injected into every
system prompt when non-empty. Write to it with `memory_write`. Persists across all sessions.

**History is global across channels** (`history.jsonl`). Recent messages are included in
context automatically. For older details, explicitly use `search_history`.

## Using `memory_write`

Call it proactively when you learn something worth keeping across sessions: user preferences,
ongoing projects, key facts, things the user asks you to remember.

Do **not** use it for ephemeral context (current task state, things already in MEMORY.md,
session-only information). Keep it durable and compact.

The tool **replaces** the entire document. Always:
1. Read `## Your Memory` from the system prompt.
2. Merge new info in — never lose existing facts.
3. Keep under ~300 words. Prefer bullet points.
4. If unsure about older conversation details, call `search_history` before writing.
