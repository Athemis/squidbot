# Implementation Plan: Prompt Toolkit Integration for CLI Channel

## Step-by-Step Implementation Order

1. **Add Dependency:**
   - Run `uv add prompt-toolkit` to add the dependency to `pyproject.toml` and update `uv.lock`.

2. **Update `RichCliChannel` in `squidbot/adapters/channels/cli.py`:**
   - Import `PromptSession` and `patch_stdout` from `prompt_toolkit`.
   - Initialize a `PromptSession` instance in `RichCliChannel.__init__` (or lazily in `receive`).
   - Modify the `receive` method to use `await self.session.prompt_async("You: ")` wrapped in an `async with patch_stdout():` block.
   - Remove the `_prompt` method and the `asyncio.to_thread` call, as `prompt_async` is natively asynchronous.
   - Ensure `EOFError` and `KeyboardInterrupt` are caught and handled by breaking the loop.

3. **Update Tests:**
   - Modify `tests/adapters/channels/test_rich_cli.py` to mock `PromptSession.prompt_async` instead of `Prompt.ask`.
   - Ensure tests cover standard input, `EOFError`, and `KeyboardInterrupt`.

4. **Quality Gates:**
   - Run `uv run ruff check .` to ensure no linting errors.
   - Run `uv run ruff format . --check` to ensure correct formatting.
   - Run `uv run mypy squidbot/` to ensure type safety.
   - Run `uv run pytest` to ensure all tests pass.

## Testing Strategy
- **Unit Tests:** Update existing tests for `RichCliChannel` to verify the new asynchronous prompt behavior.
- **Manual Verification:** Run `squidbot agent` and verify that the prompt works correctly, accepts input, and exits cleanly on Ctrl+C/Ctrl+D.

## Non-Goals
- **No multiline input:** The prompt will remain single-line.
- **No persistent history:** We will not save prompt history across sessions.
- **No full-screen UI:** The interface remains a standard scrolling terminal, not a full-screen TUI.
