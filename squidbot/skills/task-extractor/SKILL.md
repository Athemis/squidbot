---
name: task-extractor
description: "Extracts actionable tasks from unstructured messages and normalizes them into a clear checklist. Use when the user asks to derive TODOs, action items, or owners from chats, emails, or notes."
always: false
requires: {}
---

# Task Extractor

## Quick Workflow

1. Read the source content once end-to-end.
2. Extract only concrete actions (not background context).
3. Split compound requests into separate tasks.
4. Infer owner/due date only when strongly implied; otherwise mark unknown.
5. Remove duplicates and output a final normalized list.

## Output Format

- `task`: short imperative action
- `owner`: explicit owner or `unknown`
- `due`: explicit date/time or `unspecified`
- `priority`: `high`, `medium`, or `low`
- `source`: short reference to where the task came from

## Edge Cases

- If no actionable item exists, return `No actionable tasks found.`
- If timing is ambiguous, keep the task and set `due: unspecified`.
- If ownership is shared, create one task per owner when possible.
