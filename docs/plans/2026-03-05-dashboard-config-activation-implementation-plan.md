# Dashboard Config Activation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the dedicated `squidbot dashboard` command with config-driven API activation so `squidbot gateway` is the single runtime entrypoint.

**Architecture:** Add `dashboard.enabled` to settings and have `_run_gateway()` start dashboard runtime/server only when that config flag is true. Remove the `dashboard` CLI command and update tests/docs to the new contract.

**Tech Stack:** Python 3.14, cyclopts, pydantic, pytest, ruff, mypy

---

## Task 0: Add dashboard enabled flag to schema

**Files:**
- Modify: `squidbot/config/schema.py`
- Modify: `tests/config/test_dashboard_schema.py`

**Step 1: Write the failing test**

Add a new assertion in `tests/config/test_dashboard_schema.py`:

```python
def test_dashboard_settings_defaults_to_loopback() -> None:
    settings = Settings()

    assert settings.dashboard.enabled is False
    assert settings.dashboard.host == "127.0.0.1"
    assert settings.dashboard.port == 8765
```

**Step 2: Run test to verify failure**

Run: `uv run pytest tests/config/test_dashboard_schema.py -v`
Expected: FAIL because `DashboardConfig` has no `enabled` field.

**Step 3: Implement minimal schema change**

Update `DashboardConfig`:

```python
class DashboardConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
```

Keep existing loopback host validator unchanged.

**Step 4: Run test to verify pass**

Run: `uv run pytest tests/config/test_dashboard_schema.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/config/schema.py tests/config/test_dashboard_schema.py
git commit -m "feat(dashboard): add config flag for api activation"
```

---

## Task 1: Make gateway dashboard startup config-driven

**Files:**
- Modify: `squidbot/cli/gateway.py`
- Modify: `tests/adapters/test_gateway_dashboard_integration.py`
- Modify: `tests/adapters/test_gateway_run_gateway.py`

**Step 1: Write failing tests for config-gated startup**

Add/adjust tests to cover:

- Dashboard server starts when `settings.dashboard.enabled` is `True`.
- Dashboard server does not start when `settings.dashboard.enabled` is `False`.

Example assertion target:

```python
dashboard_server.assert_awaited_once()
```

for enabled case, and

```python
dashboard_server.assert_not_awaited()
```

for disabled case.

**Step 2: Run targeted tests to verify failure**

Run: `uv run pytest tests/adapters/test_gateway_dashboard_integration.py -v`
Expected: FAIL due to old `dashboard_enabled` argument contract.

**Step 3: Implement runtime change**

- In `_run_gateway`, remove `dashboard_enabled` parameter.
- Derive a local boolean from settings, e.g.:

```python
dashboard_enabled = settings.dashboard.enabled
```

- Keep all existing runtime behavior for log sink and TaskGroup startup exactly the same behind that flag.

**Step 4: Stabilize dependent tests**

Update test settings helpers (`SimpleNamespace`) to include:

```python
dashboard=SimpleNamespace(enabled=False, host="127.0.0.1", port=8765)
```

where needed.

**Step 5: Run gateway tests to verify pass**

Run: `uv run pytest tests/adapters/test_gateway_dashboard_integration.py -v`
Expected: PASS.

Run: `uv run pytest tests/adapters/test_gateway_run_gateway.py -v`
Expected: PASS.

**Step 6: Commit**

```bash
git add squidbot/cli/gateway.py tests/adapters/test_gateway_dashboard_integration.py tests/adapters/test_gateway_run_gateway.py
git commit -m "refactor(gateway): derive dashboard startup from settings"
```

---

## Task 2: Remove dashboard CLI command

**Files:**
- Modify: `squidbot/cli/main.py`
- Modify: `tests/cli/test_main_dashboard.py`

**Step 1: Write failing test updates**

Replace dashboard command test coverage with gateway contract coverage, e.g.:

```python
def test_gateway_command_runs_gateway() -> None:
    ...
```

and ensure no tests depend on `main.dashboard`.

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/cli/test_main_dashboard.py -v`
Expected: FAIL before production code is updated.

**Step 3: Implement CLI change**

- Remove `dashboard` command function from `squidbot/cli/main.py`.
- Remove command listing line from the module docstring command list.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/cli/test_main_dashboard.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/cli/main.py tests/cli/test_main_dashboard.py
git commit -m "refactor(cli): remove dedicated dashboard command"
```

---

## Task 3: Update README for new startup contract

**Files:**
- Modify: `README.md`

**Step 1: Update CLI section**

- Remove `squidbot dashboard` entry.
- Keep `squidbot gateway` entry as sole startup command.

**Step 2: Add migration/config note**

Document that dashboard API is enabled via config and started with `squidbot gateway`.

Example snippet:

```json
"dashboard": {
  "enabled": true,
  "host": "127.0.0.1",
  "port": 8765
}
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs(dashboard): switch to config-driven gateway activation"
```

---

## Task 4: Final verification

**Step 1: Run lint**

Run: `uv run ruff check .`
Expected: PASS.

**Step 2: Run formatting check**

Run: `uv run ruff format . --check`
Expected: PASS.

**Step 3: Run type checks**

Run: `uv run mypy squidbot/`
Expected: PASS.

**Step 4: Run full tests**

Run: `uv run pytest`
Expected: PASS.

**Step 5: Manual runtime smoke**

- Set `dashboard.enabled=true` in config.
- Run: `squidbot gateway`
- Verify dashboard API/web UI is reachable on configured host/port.

---

## Task 5: Optional cleanup follow-up

**Files:**
- Modify: any docs/scripts still referencing `squidbot dashboard`

**Step 1: Find remaining references**

Run: `rg "squidbot dashboard"`

**Step 2: Replace outdated references if found**

Keep wording consistent with config-driven activation.

**Step 3: Commit (if changes exist)**

```bash
git add <updated-files>
git commit -m "chore(docs): remove legacy dashboard command references"
```
