# Design: Prompt Toolkit Integration for CLI Channel

## Objective
Enhance the interactive CLI channel (`RichCliChannel`) by replacing the standard `input()`/`Prompt.ask()` with `prompt-toolkit` for asynchronous, non-blocking user input, while retaining `Rich` for all output rendering.

## Architecture Choice
- **Input:** Use `prompt-toolkit`'s `PromptSession.prompt_async()` wrapped with `patch_stdout`. This allows background tasks (like heartbeat or cron) to print to stdout without corrupting the input prompt.
- **Output:** Keep `Rich` for all output (`Console().print(Markdown(...))`). `Rich` provides excellent Markdown rendering which is essential for the assistant's responses.
- **Streaming Policy:**
  - `streaming=False` for interactive mode (`RichCliChannel`). We collect the full response before sending it to `Rich` for proper Markdown rendering.
  - `streaming=True` for single-message mode (`-m` flag, `CliChannel`). This remains unchanged.

## File-Level Changes
1. `squidbot/adapters/channels/cli.py`:
   - Update `RichCliChannel` to use `prompt-toolkit`.
   - Import `PromptSession` and `patch_stdout` from `prompt_toolkit`.
   - Replace the synchronous `_prompt` thread executor with an asynchronous `prompt_async` call.
2. `pyproject.toml` / `uv.lock`:
   - Add `prompt-toolkit` as a dependency.

## Error Handling
- Handle `EOFError` and `KeyboardInterrupt` gracefully during `prompt_async()` to allow clean exits (Ctrl+D, Ctrl+C).
- Ensure `patch_stdout` context manager correctly restores stdout state even if exceptions occur.

## Testing Approach
- Update `tests/adapters/channels/test_rich_cli.py` to mock `PromptSession.prompt_async` instead of `Prompt.ask`.
- Verify that `EOFError` and `KeyboardInterrupt` trigger a clean exit.
- Verify that standard text input yields an `InboundMessage`.

## Non-Goals
- **No multiline input:** The prompt will remain single-line.
- **No persistent history:** We will not save prompt history across sessions.
- **No full-screen UI:** The interface remains a standard scrolling terminal, not a full-screen TUI.
