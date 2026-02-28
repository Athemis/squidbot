---
name: decision-log
description: "Records decisions with context, alternatives, rationale, and follow-up actions. Use when the user asks to document why a choice was made or to preserve decision history."
always: false
requires: {}
---

# Decision Log

## Quick Workflow

1. Capture the decision statement in one sentence.
2. Record context and options considered.
3. State rationale and trade-offs explicitly.
4. Extract follow-up actions and owners.

## Output Format

- `decision`: final choice
- `context`: constraints and goals
- `options`: alternatives considered
- `rationale`: why this option won
- `actions`: follow-up tasks with owner and due date

## Edge Cases

- If options are missing, request at least one rejected alternative.
- If rationale is weak, list open assumptions.
- If no actions result, state `No follow-up actions required`.
