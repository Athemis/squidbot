# Learnings

- 2026-02-25: `JsonlMemory.load_history()` can stream safely with `deque(maxlen=last_n)` while preserving order and avoiding full-file reads.
- 2026-02-25: Opening `history.jsonl` with `errors="replace"` plus per-line safe deserialization cleanly tolerates invalid UTF-8 and malformed JSON lines.
- 2026-02-25: Shared read lock best-effort pattern works: attempt `fcntl.flock(..., LOCK_SH)`, continue unlocked on lock failure, always unlock via guarded cleanup.
- 2026-02-25: Whole-file persistence (`MEMORY.md`, `cron/jobs.json`) is safer with temp file + flush + `os.fsync` + `os.replace`.

- Added degraded-mode boundaries in `AgentLoop.run()` so memory-layer failures do not block replies.
- `build_messages` failure fallback should explicitly rebuild minimal context with only system+user.
- `persist_exchange` failures can be safely swallowed at run tail because user-visible reply is already delivered.
- For typing-compatible test doubles, subclassing `MemoryManager` avoids protocol mismatch with `AgentLoop` constructor typing.
- 2026-02-25: Corrupt `cron/jobs.json` should degrade gracefully by warning and returning `[]`, mirroring history corruption policy.
- 2026-02-25: `search_history` can stream-scan `history.jsonl` in one pass by tracking `prev` and a single pending `after` slot, preserving ±1 context while skipping malformed JSONL lines safely.

- 2026-02-25 F3 QA: `JsonlMemory.load_history()` is resilient to malformed JSONL and invalid UTF-8 bytes (`errors="replace"` + safe deserializer), and warns with skipped-line count instead of failing.
- 2026-02-25 F3 QA: `load_cron_jobs()` treats corrupt `cron/jobs.json` as non-fatal, logs a warning, and returns `[]` to keep scheduler startup responsive.
- 2026-02-25 F3 QA: `AgentLoop.run()` degrades safely when `build_messages()` or `persist_exchange()` fails; reply path remains responsive.

## JsonlMemory Improvements (2026-02-25)
- Implemented fast-path for `load_history(last_n=0)` to avoid unnecessary file I/O.
- Enhanced malformed line logging in `load_history` to include a preview of the first skipped line, making it easier to debug corrupted history files.
- Discovered that `edit` tool might require absolute paths in some environments to avoid "File not found" or line count mismatches.
