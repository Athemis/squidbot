---
name: tmux
description: Work safely with tmux sessions, panes, and captured output.
always: false
requires:
  bins: [tmux]
---

# tmux

Use this skill when you need to inspect or control long-running terminal work in a tmux session.

## When to use

- You need to check progress from a background process running inside tmux.
- You need to send a command to an existing tmux pane without attaching interactively.
- You need to capture pane output so the user can review logs or command results.

## When not to use

- You can run the command directly with the `shell` tool and wait for completion.
- You only need to read or edit files; use `read_file`, `write_file`, and `list_files` instead.
- The task can be solved with a short one-off command and does not need persistent terminal state.

## Safe command patterns

- Prefer explicit targets (`-t session:window.pane`) and verify they exist first.
- For `tmux send-keys`, send exact commands and terminate with `C-m`:
  - `tmux send-keys -t dev:0.1 "uv run pytest tests/core/test_skills.py -v" C-m`
- For `tmux capture-pane`, capture enough context and preserve line endings with `-p`:
  - `tmux capture-pane -t dev:0.1 -p -S -120`
- Avoid destructive tmux actions (`kill-session`, `kill-server`) unless the user explicitly asks.

## Squidbot examples

Use the `shell` tool for tmux commands and then report key lines back to the user.

```bash
tmux list-sessions
tmux list-panes -a -F "#{session_name}:#{window_index}.#{pane_index} #{pane_current_command}"
tmux send-keys -t dev:0.1 "uv run ruff check ." C-m
tmux capture-pane -t dev:0.1 -p -S -80
```

If tmux is missing, report that `tmux` is required and suggest running the task directly with `shell`.
