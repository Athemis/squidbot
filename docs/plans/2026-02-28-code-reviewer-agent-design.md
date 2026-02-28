# Design: Repo-Specific Code Reviewer Agent

## Date

2026-02-28

## Status

Approved

## Goal

Create a strict Python code-review agent for this repository that can be used as both a primary
agent and a subagent, while remaining read-only for source changes.

## Context

The repository defines explicit standards in `AGENTS.md`, including architecture boundaries,
typing strictness, and verification commands. The new agent should enforce these standards during
review and produce actionable findings with evidence.

## Requirements

- Language focus: Python
- Scope: Repository-specific behavior
- Access mode: `all` (primary + subagent)
- Safety: no write/edit capabilities
- Execution: optional, tightly whitelisted verification commands via bash
- Output: structured findings with severity and file references

## Approaches Considered

### A. Repo-Specific Reviewer (selected)

Use project-specific rules directly in the agent prompt.

Pros:
- Highest precision for this codebase
- Enforces architecture and tooling constraints from `AGENTS.md`
- Consistent feedback quality across sessions

Cons:
- Less reusable for other repositories

### B. Generic Python Reviewer

Use mostly language-level best practices and infer project rules dynamically.

Pros:
- Reusable across repos

Cons:
- Weaker enforcement of this repository's exact standards

### C. Two-Agent Split

Maintain both a generic Python reviewer and a squidbot-specific reviewer.

Pros:
- Strong specialization plus reuse

Cons:
- Higher maintenance overhead

## Selected Design

### Agent location

`./.opencode/agent/code-reviewer.md`

### Frontmatter

- `description`: strict Python reviewer for this repository
- `mode: all`
- `temperature: 0.1`

### Tools and permissions

Tools enabled:
- `read: true`
- `grep: true`
- `glob: true`
- `bash: true`

Tools disabled:
- `write: false`
- `edit: false`
- `webfetch: false`

Permissions:
- `write: deny`
- `edit: deny`
- `bash` whitelist only:
  - `uv run pytest*`: allow
  - `uv run ruff check .`: allow
  - `uv run ruff format . --check`: allow
  - `uv run mypy squidbot/`: allow
  - `*`: deny

### Review workflow

The agent reviews in this priority order:
1. Correctness and security issues
2. Architecture boundary violations
3. Typing discipline (`mypy --strict` expectations)
4. Test quality and coverage gaps
5. Maintainability and readability

### Output format

Each finding includes:
- Severity: `critical`, `major`, or `minor`
- Evidence: `path:line`
- Impact: why it matters
- Fix guidance: concise, actionable recommendation

If no high-impact issues are found, the agent reports that explicitly and may provide up to three
non-blocking improvements.

## Error Handling

- If a requested verification command is outside the whitelist, the agent should skip execution and
  continue with static review.
- If command execution fails, the agent reports failure context and avoids overconfident claims.

## Testing Strategy

- Create adapter tests for agent metadata loading if needed.
- Validate that the file is discoverable by the OpenCode agent loader.
- Exercise invocation in both primary and `@mention` paths to confirm `mode: all` behavior.

## Security Notes

- No file mutation tools are permitted.
- Bash permissions are restricted to non-destructive validation commands.
- Deny-all fallback is explicit for unknown bash commands.
