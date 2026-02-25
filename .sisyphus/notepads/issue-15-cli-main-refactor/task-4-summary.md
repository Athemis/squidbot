## Task 4 - Update tests to new module boundaries

Completed all requested test rewiring for gateway/onboarding boundaries.

- Updated gateway-related imports to `squidbot.cli.gateway` in:
  - `tests/adapters/test_channel_loops.py`
  - `tests/adapters/test_gateway_status.py`
  - `tests/adapters/test_llm_wiring.py`
  - `tests/adapters/test_spawn_wiring.py`
  - `tests/adapters/test_search_history_wiring.py`
- Updated bootstrap import split in `tests/adapters/test_bootstrap_wiring.py`:
  - `BOOTSTRAP_FILES_ONBOARD` stays from `squidbot.cli.main`
  - `BOOTSTRAP_FILES_MAIN`, `BOOTSTRAP_FILES_SUBAGENT`, `_load_bootstrap_prompt` now from `squidbot.cli.gateway`
- Updated onboarding test patch targets in `tests/adapters/test_onboard.py`:
  - `squidbot.cli.main.input` -> `squidbot.cli.onboard.input`
  - `squidbot.cli.main.Settings`/`Settings.load` -> `squidbot.cli.main._load_or_init_settings`
  - Removed redundant dual-patching sites; single patch target now matches lookup location.

Verification artifacts:

- Pytest run: `.sisyphus/evidence/task-4-onboard-tests.txt` (`14 passed`)
- Patch target audit: `.sisyphus/evidence/task-4-patch-targets.txt` (no matches)

Quality gates:

- LSP diagnostics are clean for all changed files.
