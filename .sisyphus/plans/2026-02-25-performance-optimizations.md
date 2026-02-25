# Performance Optimizations (squidbot)

## TL;DR
> **Summary**: Reduce per-turn latency and event-loop stalls by removing synchronous I/O from async hot paths, adding small caches with explicit invalidation rules, and avoiding O(file_size) history reads when only the last N messages are needed.
> **Deliverables**:
> - Non-blocking async tool/channel filesystem + subprocess usage (offloaded)
> - Faster `load_history(last_n=...)` that does not scan the full `history.jsonl`
> - Caching improvements for skills bodies / owner alias lookup / tool definitions
> - Lightweight, deterministic verification + optional microbench harness
> **Effort**: Medium
> **Parallel**: YES - 3 waves
> **Critical Path**: Baseline harness → remove event-loop blocking I/O → optimize history tail read → full test/typing/lint verification

## Context
### Original Request
- "Analysiere den Code auf Performance Probleme und schlage Loesungen vor."

### Interview Summary
- No interactive interview; defaults applied:
  - Primary optimization target: responsiveness (avoid event-loop blocking) and scalability with large `history.jsonl`.
  - No protocol/interface changes; keep data formats stable.
  - No new third-party dependencies unless strictly necessary.

### Research Findings
- `squidbot/adapters/persistence/jsonl.py:186` `JsonlMemory.load_history(last_n=...)` scans the entire `history.jsonl` even when only last N messages are requested (O(file_size)).
- `squidbot/adapters/tools/files.py` performs synchronous filesystem I/O inside `async def execute()` (event-loop blocking risk).
- `squidbot/adapters/channels/matrix.py` runs `subprocess.run()` (ffprobe) and sync `read_bytes()` / `write_bytes()` inside async code paths.
- `squidbot/adapters/channels/email.py:337` instantiates `MarkdownIt()` per send and reads attachment bytes synchronously.
- Skills: `squidbot/adapters/skills/fs.py` scans skill dirs each `list_skills()` call; `load_skill_body()` does sync read per prompt when `always` skills exist.
- No existing benchmark/perf harness; tests are pytest (asyncio_mode=auto). No CI detected.

### Metis Review (gaps addressed)
- Add explicit cache invalidation rules (TTL + mtime) and size guardrails.
- Avoid timing-based “must be faster” assertions in unit tests; prefer deterministic, algorithmic assertions + optional benchmark script for humans.
- Keep `MemoryPort` / `SkillsPort` / `ChannelPort` protocols unchanged.

## Work Objectives
### Core Objective
- Improve runtime responsiveness under load (large history, many skills, attachments) by eliminating event-loop blocking work and reducing unnecessary O(n) scans.

### Deliverables
- `JsonlMemory.load_history(last_n>0)` reads only the file tail (bounded reads) while preserving malformed-line tolerance.
- Async tools/channels do not execute sync filesystem/subprocess operations on the event loop.
- Caches:
  - Owner alias lookup becomes O(1).
  - Skills body reads are cached by (path, mtime).
  - Tool definitions list is cached (invalidated on register).
- Verification additions: deterministic tests + optional microbench runner.

### Definition of Done (verifiable)
- `uv run ruff check .` passes
- `uv run mypy squidbot/` passes
- `uv run pytest` passes
- Added/updated tests cover:
  - Correctness of `load_history(last_n=...)` for large files + malformed trailing lines
  - Tools/channels use `asyncio.to_thread` (or equivalent) for heavy/sync operations
  - Cache invalidation behavior (mtime/TTL) is exercised

### Must Have
- No data format changes to existing `~/.squidbot/history.jsonl`.
- No changes to port Protocol signatures.
- No event-loop blocking sync file I/O in async tool/channel paths touched by this plan.

### Must NOT Have (guardrails)
- No new persistence backend migration (e.g., SQLite) in this iteration.
- No new dependencies for benchmarking (e.g., pytest-benchmark) unless explicitly approved later.
- No global “performance assertions” in CI-like tests that are machine-speed dependent.

## Verification Strategy
> ZERO HUMAN INTERVENTION — all verification is agent-executed.
- Test decision: TDD where practical (new deterministic tests first), otherwise tests-after for mechanical refactors.
- QA policy: Each task includes happy-path + edge/failure scenario.
- Evidence: `.sisyphus/evidence/task-{N}-{slug}.txt` for benchmark outputs (optional) and profiling notes.

## Execution Strategy
### Parallel Execution Waves
Wave 1: Baseline harness + remove event-loop blocking in hot paths (Tasks 1-4)
Wave 2: Add targeted caches (Tasks 5-8)
Wave 3: Repo-wide audit + history tail-read optimization (Tasks 9-10)

### Dependency Matrix (full, all tasks)
- 1 blocks 2-10 (baseline harness informs validation)
- 2-4 can run in parallel after 1
- 5-8 can run in parallel after 1
- 9 depends on 2-8 (audit after targeted fixes)
- 10 depends on 9

### Agent Dispatch Summary
- Wave 1: 4 tasks (unspecified-high/quick)
- Wave 2: 4 tasks (quick/unspecified-high)
- Wave 3: 2 tasks (deep)

## TODOs
> Implementation + Test = ONE task. Never separate.
> EVERY task includes QA scenarios.

- [ ] 1. Add deterministic perf harness + baseline evidence

  **What to do**:
  - Add a lightweight runner that can be executed locally (no new dependencies) to capture baseline timings and produce evidence files.
  - Target operations:
    - `JsonlMemory.load_history(last_n=80)` on synthetic histories of varying sizes.
    - `FsSkillsLoader.list_skills()` and `load_skill_body()` with a synthetic skill set.
  - The runner must:
    - Create its own temp directories/files (no reliance on `~/.squidbot`).
    - Print results as stable key/value lines for easy diffing.
    - Ensure `.sisyphus/evidence/` exists and write a copy of the output to `.sisyphus/evidence/task-1-baseline.txt`.

  **Must NOT do**:
  - Do not add timing assertions to `pytest` that can fail on slower machines.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` — Reason: cross-module wiring + careful non-flaky verification
  - Skills: []
  - Omitted: [`playwright`] — no browser/UI

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: 2-10 | Blocked By: none

  **References**:
  - Persistence: `squidbot/adapters/persistence/jsonl.py:186` — `JsonlMemory.load_history()`
  - Skills loader: `squidbot/adapters/skills/fs.py:75` — `FsSkillsLoader.list_skills()` / `load_skill_body()`

  **Acceptance Criteria**:
  - [ ] `uv run python scripts/perf/perf_baseline.py` runs successfully and creates `.sisyphus/evidence/task-1-baseline.txt`

  **QA Scenarios**:
  ```
  Scenario: Baseline capture
    Tool: Bash
    Steps: uv run python scripts/perf/perf_baseline.py
    Expected: Exit 0; output includes keys for history_load_ms and skills_list_ms; evidence file exists
    Evidence: .sisyphus/evidence/task-1-baseline.txt

  Scenario: Determinism
    Tool: Bash
    Steps: uv run python scripts/perf/perf_baseline.py
    Expected: Output format stable (same keys present); values may vary but parseable
    Evidence: .sisyphus/evidence/task-1-baseline-repeat.txt
  ```

  **Commit**: YES | Message: `test(perf): add baseline perf runner` | Files: [scripts/perf/perf_baseline.py]

- [ ] 2. Make file tools non-blocking (offload sync FS work)

  **What to do**:
  - Update `ReadFileTool.execute()`, `WriteFileTool.execute()`, and `ListFilesTool.execute()` to run filesystem I/O via `asyncio.to_thread`.
  - Keep the tool interfaces and error messages stable.
  - Ensure directory listing does not block the event loop (include `iterdir()` + sorting inside the offloaded callable).
  - Add tests that deterministically prove `asyncio.to_thread` is used (monkeypatch `asyncio.to_thread` and assert it is called).

  **Must NOT do**:
  - Do not change path restriction semantics in `_resolve_safe()`.

  **Recommended Agent Profile**:
  - Category: `quick` — Reason: localized refactor + straightforward tests
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: none | Blocked By: 1

  **References**:
  - Tool code: `squidbot/adapters/tools/files.py:49` — tool `execute()` methods currently do sync FS ops
  - Testing patterns: `tests/adapters/tools/test_files.py`

  **Acceptance Criteria**:
  - [ ] `uv run pytest tests/adapters/tools/test_files.py -v` passes
  - [ ] Added tests assert `asyncio.to_thread` is called for each tool op

  **QA Scenarios**:
  ```
  Scenario: Read and list do not block loop
    Tool: Bash
    Steps: uv run pytest tests/adapters/tools/test_files.py -v
    Expected: Pass
    Evidence: .sisyphus/evidence/task-2-files-tool-tests.txt

  Scenario: Path escape rejected
    Tool: Bash
    Steps: uv run pytest tests/adapters/tools/test_files.py -k outside -v
    Expected: Pass; error mentions outside workspace
    Evidence: .sisyphus/evidence/task-2-files-tool-outside.txt
  ```

  **Commit**: YES | Message: `refactor(tools): offload file tool I/O to threads` | Files: [squidbot/adapters/tools/files.py, tests/adapters/tools/test_files.py]

- [ ] 3. Make EmailChannel send path non-blocking and reuse Markdown renderer

  **What to do**:
  - Replace per-send `MarkdownIt()` instantiation with a module-level cached instance (match Matrix style).
  - Offload attachment `read_bytes()` (and any `write_bytes()` used during attachment extraction) to `asyncio.to_thread`.
  - Ensure behavior stays identical for:
    - plain-only messages
    - mixed multipart with attachment
  - Add/extend tests to cover attachment send path (use mocks; no real SMTP).

  **Must NOT do**:
  - Do not add SMTP connection pooling in this iteration.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` — Reason: email MIME correctness + async safety
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: none | Blocked By: 1

  **References**:
  - Markdown creation: `squidbot/adapters/channels/email.py:326` (imports) and `squidbot/adapters/channels/email.py:337` (MarkdownIt().render)
  - Attachment read: `squidbot/adapters/channels/email.py:346` — sync `read_bytes()`
  - Attachment write during receive parsing: `squidbot/adapters/channels/email.py:248` — sync `dest.write_bytes(payload)`
  - Existing tests: `tests/adapters/channels/test_email.py`

  **Acceptance Criteria**:
  - [ ] `uv run pytest tests/adapters/channels/test_email.py -v` passes
  - [ ] No `MarkdownIt()` instantiation remains inside `EmailChannel.send()` (renderer is cached)

  **QA Scenarios**:
  ```
  Scenario: Email send renders Markdown once
    Tool: Bash
    Steps: uv run pytest tests/adapters/channels/test_email.py -v
    Expected: Pass
    Evidence: .sisyphus/evidence/task-3-email-tests.txt

  Scenario: Attachment send does not do sync read_bytes
    Tool: Bash
    Steps: uv run pytest tests/adapters/channels/test_email.py -k attachment -v
    Expected: Pass; test asserts asyncio.to_thread used for attachment read
    Evidence: .sisyphus/evidence/task-3-email-attachment.txt
  ```

  **Commit**: YES | Message: `refactor(email): reuse MarkdownIt and offload attachment I/O` | Files: [squidbot/adapters/channels/email.py, tests/adapters/channels/test_email.py]

- [ ] 4. Remove event-loop blocking in MatrixChannel media paths

  **What to do**:
  - Replace blocking `subprocess.run([... ffprobe ...])` with `asyncio.create_subprocess_exec` + `await proc.communicate()` and a timeout.
  - Offload `Path.read_bytes()` (upload) and `Path.write_bytes()` (download temp save) to `asyncio.to_thread`.
  - Keep behavior stable when ffprobe is missing or fails: metadata is best-effort and omissions are allowed.
  - Add tests for media metadata path using mocks:
    - Patch `asyncio.create_subprocess_exec` to return a fake process with canned JSON.
    - Assert no call site uses `subprocess.run`.

  **Must NOT do**:
  - Do not change Matrix send semantics (message formatting, thread metadata) beyond the performance refactor.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` — Reason: async subprocess + tricky mocking
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: none | Blocked By: 1

  **References**:
  - Blocking ffprobe: `squidbot/adapters/channels/matrix.py:102` — `subprocess.run(...)`
  - Sync upload read: `squidbot/adapters/channels/matrix.py:362` — `path.read_bytes()`
  - Sync download write: `squidbot/adapters/channels/matrix.py:454` — `tmp_path.write_bytes(body)`
  - Existing tests: `tests/adapters/channels/test_matrix.py`

  **Acceptance Criteria**:
  - [ ] `uv run pytest tests/adapters/channels/test_matrix.py -v` passes
  - [ ] `subprocess.run(` no longer appears in `squidbot/adapters/channels/matrix.py`

  **QA Scenarios**:
  ```
  Scenario: Matrix unit tests
    Tool: Bash
    Steps: uv run pytest tests/adapters/channels/test_matrix.py -v
    Expected: Pass
    Evidence: .sisyphus/evidence/task-4-matrix-tests.txt

  Scenario: Media metadata mocked ffprobe
    Tool: Bash
    Steps: uv run pytest tests/adapters/channels/test_matrix.py -k ffprobe -v
    Expected: Pass; test asserts asyncio.create_subprocess_exec invoked and JSON parsed
    Evidence: .sisyphus/evidence/task-4-matrix-ffprobe.txt
  ```

  **Commit**: YES | Message: `refactor(matrix): async ffprobe and offload media I/O` | Files: [squidbot/adapters/channels/matrix.py, tests/adapters/channels/test_matrix.py]

- [ ] 5. Add caching and TTL guardrails to FsSkillsLoader (list + body)

  **What to do**:
  - Add a small TTL-based cache to `FsSkillsLoader.list_skills()` so directory scans are not performed on every prompt.
    - Default TTL: 2s (hot reload remains “fast enough” but avoids per-turn scanning).
    - Implement TTL using `time.monotonic()` (not `time.time()`).
    - Invalidate immediately if any cached path’s mtime changes when a scan does occur.
  - Add a body cache for `load_skill_body(name)` keyed by resolved SKILL.md path and mtime.
  - Add tests using `tmp_path` skills:
    - List cache hit avoids repeated `iterdir/stat` heavy work (assert via monkeypatch counters).
    - Body cache hit avoids repeated `read_text`.
    - Touching SKILL.md invalidates cache.

  **Must NOT do**:
  - Do not change `SkillsPort` interface.
  - Do not change skill shadowing semantics across search dirs.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` — Reason: caching correctness + invalidation edge cases
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: 1

  **References**:
  - Loader: `squidbot/adapters/skills/fs.py:75` — `list_skills()` scan loop
  - Body read: `squidbot/adapters/skills/fs.py:99` — `load_skill_body()`
  - Core injection: `squidbot/core/memory.py:147` — skills injected each prompt
  - Tests: `tests/core/test_skills.py`

  **Acceptance Criteria**:
  - [ ] `uv run pytest tests/core/test_skills.py -v` passes
  - [ ] New tests cover list TTL + body cache + mtime invalidation

  **QA Scenarios**:
  ```
  Scenario: Cache hit
    Tool: Bash
    Steps: uv run pytest tests/core/test_skills.py -k cache -v
    Expected: Pass
    Evidence: .sisyphus/evidence/task-5-skills-cache.txt

  Scenario: Cache invalidation on touch
    Tool: Bash
    Steps: uv run pytest tests/core/test_skills.py -k invalidation -v
    Expected: Pass
    Evidence: .sisyphus/evidence/task-5-skills-invalidation.txt
  ```

  **Commit**: YES | Message: `refactor(skills): cache skill scans and bodies with TTL/mtime` | Files: [squidbot/adapters/skills/fs.py, tests/core/test_skills.py]

- [ ] 6. Optimize owner alias lookup in MemoryManager

  **What to do**:
  - Replace the per-message linear scan in `MemoryManager._is_owner()` with precomputed sets built in `__init__`:
    - `scoped_aliases: set[tuple[str, str]]` for (address, channel)
    - `unscoped_aliases: set[str]` for channel-agnostic addresses
  - Keep semantics identical to current implementation.
  - Add tests proving:
    - scoped matches override channel mismatch
    - unscoped matches work across channels
    - non-matches remain false

  **Must NOT do**:
  - Do not change label formatting in `_label_message()`.

  **Recommended Agent Profile**:
  - Category: `quick` — Reason: localized logic change + unit tests
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: 1

  **References**:
  - Current logic: `squidbot/core/memory.py:58` — `_is_owner()`
  - Message labelling: `squidbot/core/memory.py:83` — `_label_message()`
  - Tests: `tests/core/test_memory.py`

  **Acceptance Criteria**:
  - [ ] `uv run pytest tests/core/test_memory.py -v` passes

  **QA Scenarios**:
  ```
  Scenario: Owner alias semantics
    Tool: Bash
    Steps: uv run pytest tests/core/test_memory.py -k owner -v
    Expected: Pass
    Evidence: .sisyphus/evidence/task-6-owner-alias.txt

  Scenario: Label format unchanged
    Tool: Bash
    Steps: uv run pytest tests/core/test_memory.py -k label -v
    Expected: Pass
    Evidence: .sisyphus/evidence/task-6-label.txt
  ```

  **Commit**: YES | Message: `refactor(memory): precompute owner alias lookup sets` | Files: [squidbot/core/memory.py, tests/core/test_memory.py]

- [ ] 7. Cache ToolRegistry definitions list

  **What to do**:
  - Add an internal cached list of `ToolDefinition` instances in `ToolRegistry`.
  - Invalidate/update cache on `register()`.
  - Decision: store cache internally as an immutable `tuple[ToolDefinition, ...]`, and have `get_definitions()` return `list(self._cached_definitions)` so callers can’t mutate internal state.
  - Add/extend tests covering:
    - repeated `get_definitions()` calls stable
    - cache invalidation on new register

  **Must NOT do**:
  - Do not change tool execution semantics in `execute()`.

  **Recommended Agent Profile**:
  - Category: `quick` — Reason: small core refactor + unit tests
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: 1

  **References**:
  - Registry definitions: `squidbot/core/registry.py:26` — `get_definitions()`
  - Tests: `tests/core/test_registry.py`

  **Acceptance Criteria**:
  - [ ] `uv run pytest tests/core/test_registry.py -v` passes

  **QA Scenarios**:
  ```
  Scenario: Definitions cache
    Tool: Bash
    Steps: uv run pytest tests/core/test_registry.py -k definitions -v
    Expected: Pass
    Evidence: .sisyphus/evidence/task-7-registry-cache.txt
  ```

  **Commit**: YES | Message: `refactor(core): cache tool definitions in registry` | Files: [squidbot/core/registry.py, tests/core/test_registry.py]

- [ ] 8. Cache SubAgentFactory prompt assembly (avoid sync reads in SpawnTool)

  **What to do**:
  - Add caching to `SubAgentFactory.build()` prompt assembly so repeated spawns do not reread bootstrap files and profile system prompt files each time.
  - Cache keys:
    - Bootstrap prompt cache keyed by tuple(filenames) + mtimes of existing files
    - system_prompt_file cache keyed by file path + mtime
  - Keep behavior stable when files are missing (skip silently).
  - Add tests verifying:
    - repeated `build()` does not reread files if mtimes unchanged (patch `Path.read_text` to count calls)
    - touching a file causes reread

  **Must NOT do**:
  - Do not make `SubAgentFactory.build()` async (avoid signature ripple).

  **Recommended Agent Profile**:
  - Category: `unspecified-high` — Reason: caching correctness + careful mocking
  - Skills: []

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: none | Blocked By: 1

  **References**:
  - Prompt assembly: `squidbot/adapters/tools/spawn.py:178` — `SubAgentFactory.build()`
  - Bootstrap reads: `squidbot/adapters/tools/spawn.py:116` — `_load_bootstrap_prompt()`
  - Profile prompt file read: `squidbot/adapters/tools/spawn.py:212` — `profile.system_prompt_file` read
  - Tests: `tests/adapters/tools/test_spawn.py`

  **Acceptance Criteria**:
  - [ ] `uv run pytest tests/adapters/tools/test_spawn.py -v` passes

  **QA Scenarios**:
  ```
  Scenario: Spawn prompt caching
    Tool: Bash
    Steps: uv run pytest tests/adapters/tools/test_spawn.py -k prompt -v
    Expected: Pass
    Evidence: .sisyphus/evidence/task-8-spawn-cache.txt

  Scenario: Cache invalidation
    Tool: Bash
    Steps: uv run pytest tests/adapters/tools/test_spawn.py -k invalidation -v
    Expected: Pass
    Evidence: .sisyphus/evidence/task-8-spawn-invalidation.txt
  ```

  **Commit**: YES | Message: `refactor(spawn): cache prompt assembly by mtime` | Files: [squidbot/adapters/tools/spawn.py, tests/adapters/tools/test_spawn.py]

- [ ] 9. Repo-wide audit: eliminate remaining sync FS/subprocess calls in async paths (bounded scope)

  **What to do**:
  - Add a small audit script `scripts/perf/audit_async_blocking.py` that fails (exit code != 0) if it finds:
    - Any `subprocess.run(` in production code under `squidbot/` (exclude `tests/`).
    - Any direct filesystem calls in the hot-path modules unless explicitly offloaded via `asyncio.to_thread` on the same line:
      - `read_text(`, `write_text(`, `read_bytes(`, `write_bytes(`, `iterdir(`
      - Scope: `squidbot/adapters/tools/`, `squidbot/adapters/channels/`, `squidbot/adapters/persistence/`
  - Run the audit script and save its output to `.sisyphus/evidence/task-9-audit.txt`.
  - If the audit fails:
    - Fix the flagged call sites by offloading (`asyncio.to_thread`) or switching to async subprocess.
    - Re-run until the audit passes.

  **Must NOT do**:
  - Do not refactor large modules “because you’re there”; only fix blocking calls discovered by the audit.

  **Recommended Agent Profile**:
  - Category: `deep` — Reason: cross-cutting audit + careful boundary decisions
  - Skills: []

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: 10 | Blocked By: 2-8

  **References**:
  - Known tool hot path: `squidbot/adapters/tools/files.py`
  - Known channel hot paths: `squidbot/adapters/channels/matrix.py`, `squidbot/adapters/channels/email.py`

  **Acceptance Criteria**:
  - [ ] `uv run python scripts/perf/audit_async_blocking.py | tee .sisyphus/evidence/task-9-audit.txt` exits 0
  - [ ] `uv run pytest` passes

  **QA Scenarios**:
  ```
  Scenario: Audit passes
    Tool: Bash
    Steps: uv run python scripts/perf/audit_async_blocking.py | tee .sisyphus/evidence/task-9-audit.txt
    Expected: Exit 0; output ends with OK
    Evidence: .sisyphus/evidence/task-9-audit.txt

  Scenario: Full suite
    Tool: Bash
    Steps: uv run pytest
    Expected: Pass
    Evidence: .sisyphus/evidence/task-9-pytest.txt
  ```

  **Commit**: YES | Message: `chore(perf): add audit for blocking async operations` | Files: [scripts/perf/audit_async_blocking.py]

- [ ] 10. Optimize `JsonlMemory.load_history(last_n)` to avoid scanning full file

  **What to do**:
  - Implement a tail-reading strategy for `load_history(last_n>0)`:
    - Open `history.jsonl` in binary mode.
    - Read fixed-size blocks from the end moving backwards (block size: 64 KiB).
    - Stopping rule (decision): keep expanding backwards until either:
      - you have parsed at least `last_n` valid messages (skipping malformed/empty lines), or
      - you reach the beginning of the file.
    - Implementation hint (non-binding): start by collecting roughly `(last_n + 10)` candidate lines, parse, and only read more blocks if you still have fewer than `last_n` valid messages.
    - Decode candidate lines individually as UTF-8 with `errors='replace'`.
    - Parse with `deserialize_message_safe`; skip malformed lines.
    - Return messages in chronological order.
  - Keep existing behavior for `last_n is None` (full scan) and `last_n <= 0` (return []).
  - Add deterministic tests that prove we do not read the full file:
    - Create a synthetic JSONL history large enough that full scans are expensive (e.g., >= 8 MiB) with small, fixed-size lines.
    - Patch `pathlib.Path.open` (for the binary tail-read path only) to return a wrapper around the real file object that counts total bytes read via `read()`.
    - Assert bytes read is substantially less than file size for `last_n=80` (choose an explicit assertion for the synthetic file, e.g., `bytes_read <= 1_048_576`).
  - Preserve best-effort shared locking semantics (`LOCK_SH`) as in current implementation.

  **Must NOT do**:
  - Do not change JSONL serialization format or message schema.
  - Do not remove malformed-line tolerance.

  **Recommended Agent Profile**:
  - Category: `deep` — Reason: tricky file tail parsing + concurrency correctness
  - Skills: []

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: none | Blocked By: 9

  **References**:
  - Current implementation: `squidbot/adapters/persistence/jsonl.py:186` — `load_history()`
  - Safe parse: `squidbot/adapters/persistence/jsonl.py:93` — `deserialize_message_safe()`
  - Tests: `tests/adapters/persistence/test_jsonl.py`

  **Acceptance Criteria**:
  - [ ] `uv run pytest tests/adapters/persistence/test_jsonl.py -v` passes
  - [ ] New tests demonstrate bounded reads for `last_n>0`
  - [ ] `uv run pytest` passes

  **QA Scenarios**:
  ```
  Scenario: Tail read returns correct last messages
    Tool: Bash
    Steps: uv run pytest tests/adapters/persistence/test_jsonl.py -k last_n -v
    Expected: Pass
    Evidence: .sisyphus/evidence/task-10-jsonl-last-n.txt

  Scenario: Malformed trailing line tolerated
    Tool: Bash
    Steps: uv run pytest tests/adapters/persistence/test_jsonl.py -k malformed -v
    Expected: Pass
    Evidence: .sisyphus/evidence/task-10-jsonl-malformed.txt
  ```

  **Commit**: YES | Message: `fix(persistence): tail-read history for last_n loads` | Files: [squidbot/adapters/persistence/jsonl.py, tests/adapters/persistence/test_jsonl.py]

## Final Verification Wave (4 parallel agents, ALL must APPROVE)
- [ ] F1. Plan Compliance Audit — oracle
- [ ] F2. Code Quality Review — unspecified-high
- [ ] F3. Real Manual QA — unspecified-high (+ playwright if UI)
- [ ] F4. Scope Fidelity Check — deep

## Commit Strategy
- Prefer small atomic commits per logical improvement area:
  - `fix(persistence): ...`, `refactor(tools): ...`, `refactor(memory): ...`, etc.

## Success Criteria
- No correctness regressions (tests/types/lint clean)
- Reduced perceived latency in interactive usage; no obvious event-loop stalls on file reads / attachment sends
- `load_history(last_n=...)` scales with last_n rather than file size
