# Dashboard Web Interface Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a localhost-only operator dashboard that runs with the gateway, with monitoring, live log tail (including "load older"), targeted config editing, explicit restart intent, and non-polling streamed operator chat.

**Architecture:** Add a FastAPI dashboard API that reuses gateway runtime state and `AgentLoop`. Serve package-owned frontend assets built from a Svelte + TypeScript + Vite project. Keep mutating routes local-write-safe through loopback host/origin checks and a runtime nonce.

**Tech Stack:** Python 3.14, FastAPI, Uvicorn, Svelte 5, TypeScript, Vite

---

## Task 0: Add required dashboard dependencies and import gate

**Files:**
- Modify: `pyproject.toml`
- Create: `squidbot/adapters/dashboard/api.py`
- Create: `tests/adapters/test_dashboard_imports.py`

**Step 1: Write the failing test**

```python
def test_dashboard_app_factory_imports() -> None:
    from squidbot.adapters.dashboard.api import build_dashboard_app

    assert callable(build_dashboard_app)
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/adapters/test_dashboard_imports.py -v`
Expected: FAIL because FastAPI/Uvicorn deps and modules are not wired yet.

**Step 3: Implement minimal dependency changes**

- Add `fastapi` and `uvicorn` to `project.dependencies` in `pyproject.toml`.
- Add minimal API module stub so import gate validates dependency wiring, not missing file order:

```python
def build_dashboard_app() -> FastAPI:
    app = FastAPI(title="squidbot dashboard")
    return app
```

**Step 4: Run test to verify pass**

Run: `uv run pytest tests/adapters/test_dashboard_imports.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add pyproject.toml squidbot/adapters/dashboard/api.py tests/adapters/test_dashboard_imports.py
git commit -m "deps(dashboard): add fastapi and uvicorn runtime dependencies"
```

---

## Task 1: Add dashboard command and dashboard server config

**Files:**
- Modify: `squidbot/config/schema.py`
- Modify: `squidbot/cli/main.py`
- Create: `tests/cli/test_main_dashboard.py`

**Step 1: Write the failing tests**

Add tests for:
- `dashboard` CLI command exists and calls `_run_gateway(..., dashboard_enabled=True)`.
- config model has dashboard host/port defaults (`127.0.0.1`, chosen port).
- config model rejects non-loopback host values.

```python
def test_dashboard_command_runs_gateway_with_dashboard_enabled() -> None:
    with (
        patch("squidbot.cli.main._setup_logging") as setup,
        patch("squidbot.cli.main.asyncio.run") as run,
        patch("squidbot.cli.main._run_gateway", return_value=AsyncMock()),
    ):
        dashboard()
    setup.assert_called_once_with("INFO")
    run.assert_called_once()
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/cli/test_main_dashboard.py -v`
Expected: FAIL because command/config are missing.

**Step 3: Implement minimal command/config**

- Add dashboard config block to `Settings` schema (`host`, `port`).
- Validate host as loopback-only (`127.0.0.1`/`localhost`) to preserve localhost-only scope.
- Add `dashboard` command in `squidbot/cli/main.py`.

```python
@app.command
def dashboard(config: Path = DEFAULT_CONFIG_PATH, log_level: str = "INFO") -> None:
    _setup_logging(log_level)
    asyncio.run(_run_gateway(config_path=config, dashboard_enabled=True))
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/cli/test_main_dashboard.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/config/schema.py squidbot/cli/main.py tests/cli/test_main_dashboard.py
git commit -m "feat(dashboard): add CLI command and dashboard config"
```

---

## Task 2: Add bounded dashboard log buffer with cursor paging

**Files:**
- Create: `squidbot/adapters/dashboard/logs.py`
- Create: `tests/adapters/test_dashboard_logs.py`

**Step 1: Write failing tests**

```python
def test_log_buffer_returns_newest_slice_and_cursor() -> None: ...
def test_log_buffer_loads_older_entries_from_cursor() -> None: ...
def test_log_buffer_drops_oldest_when_full() -> None: ...
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/adapters/test_dashboard_logs.py -v`
Expected: FAIL because module does not exist.

**Step 3: Implement minimal log buffer**

Implement immutable entry/page models and `DashboardLogBuffer` with thread-safe append/page operations.

```python
class DashboardLogBuffer:
    def append(self, *, level: str, message: str) -> None: ...
    def page(self, *, limit: int, before_cursor: int | None = None) -> DashboardLogPage: ...
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/adapters/test_dashboard_logs.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/adapters/dashboard/logs.py tests/adapters/test_dashboard_logs.py
git commit -m "feat(dashboard): add bounded log buffer"
```

---

## Task 3: Add dashboard runtime and bootstrap endpoint (nonce + local safety)

**Files:**
- Create: `squidbot/adapters/dashboard/runtime.py`
- Modify: `squidbot/adapters/dashboard/api.py`
- Modify: `squidbot/adapters/dashboard/__init__.py`
- Create: `tests/adapters/test_dashboard_api_security.py`

**Step 1: Write failing tests**

Add tests for:
- `GET /api/bootstrap` returns runtime nonce.
- mutating routes reject invalid host/origin/nonce.
- loopback-origin writes with valid nonce pass route guard.

```python
def test_bootstrap_returns_local_nonce(client: TestClient) -> None: ...
def test_patch_config_rejects_missing_nonce(client: TestClient) -> None: ...
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/adapters/test_dashboard_api_security.py -v`
Expected: FAIL because API/runtime do not exist.

**Step 3: Implement runtime + guard helpers**

- Add `DashboardRuntime` with:
  - `GatewayState`
  - `DashboardLogBuffer`
  - config path
  - local nonce
  - restart-intent timestamp/state
- Add guard function used by mutating handlers.

```python
def require_local_write(request: Request, runtime: DashboardRuntime) -> None: ...
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/adapters/test_dashboard_api_security.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/adapters/dashboard/runtime.py squidbot/adapters/dashboard/api.py squidbot/adapters/dashboard/__init__.py tests/adapters/test_dashboard_api_security.py
git commit -m "feat(dashboard): add runtime bootstrap and local write-safety guards"
```

---

## Task 4: Implement overview/logs/config/restart-intent APIs

**Files:**
- Modify: `squidbot/adapters/dashboard/api.py`
- Create: `tests/adapters/test_dashboard_api.py`

**Step 1: Write failing API tests**

Cover:
- `GET /api/overview`
- `GET /api/logs?limit=200&before=<cursor>`
- `GET /api/config`
- `PATCH /api/config`
- `POST /api/config/restart-intent`

```python
def test_post_restart_intent_acknowledges_intent(client: TestClient) -> None:
    response = client.post("/api/config/restart-intent", headers=valid_headers)
    assert response.status_code == 200
    assert response.json()["acknowledged"] is True
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/adapters/test_dashboard_api.py -v`
Expected: FAIL before endpoints are implemented.

**Step 3: Implement minimal handlers**

- Keep v1 editable config subset only:
  - `channels.matrix.enabled`
  - `channels.email.enabled`
  - `agents.heartbeat.enabled`
  - `agents.heartbeat.interval_minutes`
- return deterministic validation errors.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/adapters/test_dashboard_api.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/adapters/dashboard/api.py tests/adapters/test_dashboard_api.py
git commit -m "feat(dashboard): add overview logs config and restart-intent APIs"
```

---

## Task 5: Add streamed operator chat endpoint with disconnect safety

**Files:**
- Create: `squidbot/adapters/dashboard/chat.py`
- Modify: `squidbot/adapters/dashboard/runtime.py`
- Modify: `squidbot/adapters/dashboard/api.py`
- Create: `tests/adapters/test_dashboard_chat_stream.py`

**Step 1: Write failing tests**

Test:
- emits chunk frames and done frame in order.
- emits error frame on exception.
- disconnect path cancels producer/cleanup without leaked tasks.

```python
def test_chat_stream_disconnect_cancels_producer(...) -> None: ...
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/adapters/test_dashboard_chat_stream.py -v`
Expected: FAIL because chat stream endpoint is missing.

**Step 3: Implement streaming bridge**

- Add ChannelPort-compatible streaming adapter for dashboard.
- Use `StreamingResponse` with line-delimited JSON frames.
- enforce local write-safety guard for chat POST.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/adapters/test_dashboard_chat_stream.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/adapters/dashboard/chat.py squidbot/adapters/dashboard/runtime.py squidbot/adapters/dashboard/api.py tests/adapters/test_dashboard_chat_stream.py
git commit -m "feat(dashboard): add streamed operator chat with disconnect cleanup"
```

---

## Task 6: Add gateway lifecycle seam and dashboard runtime wiring

**Files:**
- Modify: `squidbot/cli/gateway.py`
- Create: `tests/adapters/test_gateway_dashboard_integration.py`

**Step 1: Write failing tests**

Use a deterministic seam (shutdown event/cancellation hook) rather than awaiting `_run_gateway()` forever.

```python
async def test_gateway_starts_dashboard_server_and_stops_on_shutdown() -> None: ...
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/adapters/test_gateway_dashboard_integration.py -v`
Expected: FAIL because lifecycle seam is missing.

**Step 3: Implement wiring with testable lifecycle**

- Extend `_run_gateway(..., dashboard_enabled: bool = False, shutdown_event: asyncio.Event | None = None)`.
- Build `DashboardRuntime` when enabled.
- Add log sink mirroring to `DashboardLogBuffer`.
- Start Uvicorn server in TaskGroup and support controlled shutdown for tests.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/adapters/test_gateway_dashboard_integration.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add squidbot/cli/gateway.py tests/adapters/test_gateway_dashboard_integration.py
git commit -m "feat(dashboard): wire gateway runtime and testable dashboard lifecycle"
```

---

## Task 7: Build Svelte frontend and adaptive polling stores

**Files:**
- Create: `web/dashboard/package.json`
- Create: `web/dashboard/tsconfig.json`
- Create: `web/dashboard/vite.config.ts`
- Create: `web/dashboard/src/main.ts`
- Create: `web/dashboard/src/App.svelte`
- Create: `web/dashboard/src/lib/api.ts`
- Create: `web/dashboard/src/lib/polling.ts`
- Create: `web/dashboard/src/routes/*.svelte`
- Create: `web/dashboard/src/lib/polling.test.ts`
- Create: `web/dashboard/src/lib/api.test.ts`

**Step 1: Write failing frontend unit tests**

Add tests for:
- adaptive polling interval switches on visibility changes.
- mutating API requests include `X-Squidbot-Local-Nonce`.

```ts
it("uses 2s polling for visible and 15s for hidden", () => {
  expect(choosePollingIntervalMs("visible")).toBe(2000)
  expect(choosePollingIntervalMs("hidden")).toBe(15000)
})

it("adds nonce header on patch config", async () => {
  await patchConfig(payload, "nonce-123")
  expect(fetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({
    headers: expect.objectContaining({ "X-Squidbot-Local-Nonce": "nonce-123" }),
  }))
})
```

**Step 2: Run build to verify failure**

Run: `npm --prefix web/dashboard run test`
Expected: FAIL because frontend project/tests do not exist yet.

**Step 3: Implement minimal frontend**

- pages: Overview, Logs, Config, Chat.
- adaptive polling utility:

```ts
export function choosePollingIntervalMs(): number {
  return document.visibilityState === "visible" ? 2000 : 15000;
}
```

- bootstrap nonce fetched once and attached to mutating requests.
- logs page starts at 200 lines and supports "Load older".
- chat page consumes streamed frames.
- add frontend test runner (`vitest`) and make tests pass.

**Step 4: Run tests and build/type checks**

Run: `npm --prefix web/dashboard run test`
Expected: PASS.

Run: `npm --prefix web/dashboard run build`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/dashboard
git commit -m "feat(dashboard-ui): add Svelte frontend for overview logs config and chat"
```

---

## Task 8: Package frontend assets into squidbot and serve from package path

**Files:**
- Modify: `pyproject.toml`
- Modify: `squidbot/adapters/dashboard/api.py`
- Create: `squidbot/adapters/dashboard/static/.gitkeep`
- Create: `scripts/build_dashboard_assets.py` (or equivalent helper)
- Create: `tests/adapters/test_dashboard_static_assets.py`
- Create: `tests/integration/test_dashboard_packaging_smoke.py`

**Step 1: Write failing tests**

```python
def test_dashboard_root_serves_packaged_index_html(client: TestClient) -> None: ...
def test_missing_packaged_assets_returns_clear_error(client: TestClient) -> None: ...
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/adapters/test_dashboard_static_assets.py -v`
Expected: FAIL before packaging/static wiring.

**Step 3: Implement packaging path**

- Add build helper that copies `web/dashboard/dist/*` to `squidbot/adapters/dashboard/static/`.
- Include static directory in package data via `pyproject.toml`.
- FastAPI serves static files from package path and SPA fallback.
- Add CI packaging smoke command sequence to docs/plan:
  - build frontend
  - copy packaged assets
  - build python artifact
  - install artifact in clean env
  - verify dashboard `/` serves packaged HTML

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/adapters/test_dashboard_static_assets.py -v`
Expected: PASS.

Run: `uv run pytest tests/integration/test_dashboard_packaging_smoke.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add pyproject.toml squidbot/adapters/dashboard/api.py squidbot/adapters/dashboard/static/.gitkeep scripts/build_dashboard_assets.py tests/adapters/test_dashboard_static_assets.py tests/integration/test_dashboard_packaging_smoke.py
git commit -m "feat(dashboard-ui): package and serve frontend assets from squidbot package"
```

---

## Task 9: Add CI dashboard gates

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/build_dashboard_assets.py` (if CI helper flags are needed)
- Create: `tests/integration/test_dashboard_packaging_smoke.py` (if not already created)
- Create: `scripts/smoke_dashboard_install.py`
- Create: `docs/ci/dashboard-checks.md`

**Step 1: Write failing CI-oriented checks (local reproduction)**

Define reproducible local gate sequence matching CI target:

```bash
npm --prefix web/dashboard run test
npm --prefix web/dashboard run build
python scripts/build_dashboard_assets.py
uv build
python -m venv .tmp_dashboard_smoke
.tmp_dashboard_smoke/bin/pip install dist/*.whl
```

Expected (pre-task): FAIL because CI workflow does not enforce dashboard gates.

**Step 2: Implement CI workflow changes**

- Add dashboard CI steps for:
  - frontend test/build
  - asset copy helper
  - python artifact build
  - installed-artifact smoke test
- Ensure workflow fails if packaged `index.html` is missing.
- Define required check names emitted by workflow jobs:
  - `dashboard-frontend`
  - `dashboard-package-smoke`

**Step 2.5: Configure and verify branch protection mapping**

- Ensure repository branch protection requires:
  - `dashboard-frontend`
  - `dashboard-package-smoke`
- Record ownership and check-name mapping in `docs/ci/dashboard-checks.md`.
- Require maintainer review when `docs/ci/dashboard-checks.md` or dashboard CI job names change.

**Step 3: Verify CI workflow locally (best effort)**

Run local command sequence from Step 1 and integration smoke test:

Run: `python scripts/smoke_dashboard_install.py --wheel dist/*.whl`
Expected: PASS.

Acceptance criterion: A test PR with a failing dashboard job is not mergeable.

**Step 4: Commit**

```bash
git add .github/workflows/ci.yml scripts/build_dashboard_assets.py scripts/smoke_dashboard_install.py docs/ci/dashboard-checks.md tests/integration/test_dashboard_packaging_smoke.py
git commit -m "ci(dashboard): enforce frontend and installed-artifact dashboard gates"
```

---

## Task 10: Documentation and operator usage updates

**Files:**
- Modify: `README.md`
- Modify: `docs/plans/2026-03-05-dashboard-web-interface-design.md` (status/update notes if needed)

**Step 1: Write docs assertions checklist**

Ensure docs cover:
- how to build frontend assets
- how to run `squidbot dashboard`
- localhost write-safety behavior (nonce/origin)
- restart-intent semantics

**Step 2: Update docs**

Add clear command sequence:

```bash
npm --prefix web/dashboard install
npm --prefix web/dashboard run build
python scripts/build_dashboard_assets.py
squidbot dashboard
```

**Step 3: Commit**

```bash
git add README.md docs/plans/2026-03-05-dashboard-web-interface-design.md
git commit -m "docs(dashboard): document local build run and write-safety model"
```

---

## Task 11: Final verification

**Step 1: Run lint**

Run: `uv run ruff check .`
Expected: PASS.

**Step 2: Run formatting check**

Run: `uv run ruff format . --check`
Expected: PASS.

**Step 3: Run type checks**

Run: `uv run mypy squidbot/`
Expected: PASS.

**Step 4: Run tests**

Run: `uv run pytest`
Expected: PASS.

**Step 5: Run frontend tests/build + asset copy**

Run: `npm --prefix web/dashboard run test`
Expected: PASS.

Run: `npm --prefix web/dashboard run build && python scripts/build_dashboard_assets.py`
Expected: PASS.

**Step 6: Packaging smoke gate (installed artifact)**

Run: `uv build`
Expected: PASS.

Run: `uv tool install --reinstall dist/*.whl`
Expected: PASS.

Run: `python scripts/smoke_dashboard_install.py --wheel dist/*.whl`
Expected: PASS.

**Step 7: Manual smoke test**

Run: `squidbot dashboard`
Expected:
- dashboard reachable on `http://127.0.0.1:<port>`
- overview refreshes adaptively
- logs show newest 200 and load older entries
- config save sets restart-required where relevant
- restart-intent endpoint reflects explicit operator action
- chat streams response without polling
- mutating calls fail with invalid nonce/origin
