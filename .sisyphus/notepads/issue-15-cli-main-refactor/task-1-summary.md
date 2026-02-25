# Task 1 Summary: Audit impacted imports and patch targets

## Impacted Imports
The following files import from `squidbot.cli.main`:
- `tests/adapters/test_llm_wiring.py`: `_resolve_llm`
- `tests/adapters/test_channel_loops.py`: `GatewayState`, `_channel_loop`, `_channel_loop_with_state`
- `tests/adapters/test_bootstrap_wiring.py`: (Multiple imports in a block)
- `tests/adapters/test_onboard.py`: `BOOTSTRAP_FILES_MAIN`, `_run_onboard`

## Impacted Patches
The following patches target `squidbot.cli.main`:
- `tests/adapters/test_onboard.py`:
    - `squidbot.cli.main.input`
    - `squidbot.cli.main.Settings`
    - `squidbot.cli.main.Settings.load`

## Checklist for Updates
- [ ] Update `tests/adapters/test_llm_wiring.py` imports/patches.
- [ ] Update `tests/adapters/test_channel_loops.py` imports/patches.
- [ ] Update `tests/adapters/test_bootstrap_wiring.py` imports/patches.
- [ ] Update `tests/adapters/test_onboard.py` imports/patches.
