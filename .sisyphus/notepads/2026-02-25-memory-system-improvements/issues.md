# Issues

- 2026-02-25: No functional blockers encountered during JsonlMemory hardening; targeted adapter tests passed after implementation.

- Initial memory test doubles were not typed as `MemoryManager`, causing LSP incompatibility in `AgentLoop` tests.
- Override signatures in `MemoryManager` subclasses must keep positional parameters to match base methods.

- 2026-02-25 F3 QA: `search_history._scan_history()` does best-effort parsing with malformed-line skipping but performs unlocked reads; correctness relies on line-atomic append behavior and safe-deserialize skip semantics during concurrent writes.
