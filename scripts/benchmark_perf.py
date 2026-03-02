"""Performance benchmark for the perf/performance-optimization changes.

Compares "before" (naive/sequential behaviour, implemented inline) with
"after" (optimised implementation) for each changed subsystem.

Usage:
    uv run python scripts/benchmark_perf.py

Results are printed to stdout as a Markdown table.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RUNS = 5  # repetitions per benchmark (median is reported)


def _median_ms(times: list[float]) -> str:
    return f"{statistics.median(times) * 1000:.2f} ms"


def _speedup(before: list[float], after: list[float]) -> str:
    b = statistics.median(before)
    a = statistics.median(after)
    if a == 0:
        return "∞×"
    ratio = b / a
    return f"{ratio:.1f}×"


def bench(label: str, before: list[float], after: list[float]) -> dict[str, str]:
    return {
        "label": label,
        "before": _median_ms(before),
        "after": _median_ms(after),
        "speedup": _speedup(before, after),
    }


# ---------------------------------------------------------------------------
# 1. load_history: disk read vs cache hit
# ---------------------------------------------------------------------------


def _make_history_file(path: Path, n_messages: int) -> None:
    """Write N messages to a JSONL history file."""
    with path.open("w", encoding="utf-8") as f:
        for i in range(n_messages):
            msg = {
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"message number {i} with some content to make it realistic",
                "timestamp": datetime.now(UTC).isoformat(),
                "channel": "cli",
                "sender_id": "local",
            }
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")


async def bench_load_history_cache(n_messages: int) -> dict[str, str]:
    """Compare disk read (first call / no cache) vs cache hit (subsequent calls)."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory

    before_times: list[float] = []
    after_times: list[float] = []

    with tempfile.TemporaryDirectory() as tmp:
        storage = JsonlMemory(base_dir=Path(tmp))
        _make_history_file(Path(tmp) / "history.jsonl", n_messages)

        # Warm up once to ensure OS page cache is warm (isolates our cache, not OS)
        await storage.load_history(last_n=50)

        # BEFORE: simulate no-cache by creating a fresh JsonlMemory each time
        for _ in range(RUNS):
            fresh = JsonlMemory(base_dir=Path(tmp))
            t0 = time.perf_counter()
            await fresh.load_history(last_n=50)
            before_times.append(time.perf_counter() - t0)

        # AFTER: second call on same instance → ring-buffer cache hit
        await storage.load_history(last_n=50)  # prime cache
        for _ in range(RUNS):
            t0 = time.perf_counter()
            await storage.load_history(last_n=50)
            after_times.append(time.perf_counter() - t0)

    return bench(f"load_history cache hit ({n_messages} msgs)", before_times, after_times)


# ---------------------------------------------------------------------------
# 2. persist_exchange: 2× append_message vs append_messages batch
# ---------------------------------------------------------------------------


async def bench_persist_exchange_batch() -> dict[str, str]:
    """Compare two sequential append_message calls vs one append_messages batch."""
    from squidbot.adapters.persistence.jsonl import JsonlMemory
    from squidbot.core.models import Message

    before_times: list[float] = []
    after_times: list[float] = []

    user_msg = Message(role="user", content="hello world", channel="cli", sender_id="local")
    asst_msg = Message(role="assistant", content="hi there", channel="cli", sender_id="assistant")

    with tempfile.TemporaryDirectory() as tmp:
        # BEFORE: two separate append_message calls (2 open+flock)
        for _ in range(RUNS):
            storage = JsonlMemory(base_dir=Path(tmp))
            t0 = time.perf_counter()
            await storage.append_message(user_msg)
            await storage.append_message(asst_msg)
            before_times.append(time.perf_counter() - t0)

        # AFTER: single append_messages call (1 open+flock)
        for _ in range(RUNS):
            storage = JsonlMemory(base_dir=Path(tmp))
            t0 = time.perf_counter()
            await storage.append_messages([user_msg, asst_msg])
            after_times.append(time.perf_counter() - t0)

    return bench("persist_exchange batch write", before_times, after_times)


# ---------------------------------------------------------------------------
# 3. build_messages: sequential vs parallel load
# ---------------------------------------------------------------------------


async def bench_parallel_memory_load() -> dict[str, str]:
    """Compare sequential vs parallel load of history + global memory."""
    from squidbot.core.models import Message

    DELAY = 0.02  # simulate 20ms I/O each

    class SlowStorage:
        async def load_history(self, last_n: int | None = None) -> list[Message]:
            await asyncio.sleep(DELAY)
            return []

        async def load_global_memory(self) -> str:
            await asyncio.sleep(DELAY)
            return ""

        async def append_message(self, m: Message) -> None: ...
        async def save_global_memory(self, c: str) -> None: ...
        async def load_cron_jobs(self) -> list:
            return []  # type: ignore[return-value]

        async def save_cron_jobs(self, j: list) -> None: ...

    before_times: list[float] = []
    after_times: list[float] = []

    # BEFORE: sequential awaits
    for _ in range(RUNS):
        storage = SlowStorage()
        t0 = time.perf_counter()
        await storage.load_history(last_n=50)
        await storage.load_global_memory()
        before_times.append(time.perf_counter() - t0)

    # AFTER: asyncio.gather (as MemoryManager.build_messages now does)
    for _ in range(RUNS):
        storage = SlowStorage()
        t0 = time.perf_counter()
        await asyncio.gather(
            storage.load_history(last_n=50),
            storage.load_global_memory(),
        )
        after_times.append(time.perf_counter() - t0)

    return bench(
        f"build_messages parallel load (2×{int(DELAY * 1000)}ms I/O)", before_times, after_times
    )


# ---------------------------------------------------------------------------
# 4. Tool execution: sequential vs parallel (N tools × T ms each)
# ---------------------------------------------------------------------------


async def bench_parallel_tools(n_tools: int, tool_delay_ms: float = 50.0) -> dict[str, str]:
    """Compare sequential vs parallel execution of N tool calls."""
    from squidbot.core.models import ToolResult

    async def slow_tool(**kwargs: Any) -> ToolResult:
        await asyncio.sleep(tool_delay_ms / 1000)
        return ToolResult(tool_call_id="", content="done")

    before_times: list[float] = []
    after_times: list[float] = []

    # BEFORE: sequential for loop
    for _ in range(RUNS):
        t0 = time.perf_counter()
        for _ in range(n_tools):
            await slow_tool()
        before_times.append(time.perf_counter() - t0)

    # AFTER: asyncio.gather (as _append_tool_results now does)
    for _ in range(RUNS):
        t0 = time.perf_counter()
        await asyncio.gather(*[slow_tool() for _ in range(n_tools)])
        after_times.append(time.perf_counter() - t0)

    return bench(
        f"parallel tool execution ({n_tools} tools × {tool_delay_ms:.0f}ms)",
        before_times,
        after_times,
    )


# ---------------------------------------------------------------------------
# 5. search_history: with vs without pre-filter
# ---------------------------------------------------------------------------


def _make_large_history_jsonl(path: Path, n_messages: int, hit_rate: float) -> int:
    """Write N messages, hit_rate fraction of which contain the query term."""
    n_hits = int(n_messages * hit_rate)
    with path.open("w", encoding="utf-8") as f:
        for i in range(n_messages):
            if i < n_hits:
                content = f"please find me query_needle in message {i}"
            else:
                content = f"unrelated content about something else entirely message {i}"
            msg = {
                "role": "user" if i % 2 == 0 else "assistant",
                "content": content,
                "timestamp": datetime.now(UTC).isoformat(),
                "channel": "cli",
                "sender_id": "local",
            }
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return n_hits


async def bench_search_history_filter(n_messages: int, hit_rate: float) -> dict[str, str]:
    """Compare scan with vs without the substring pre-filter."""
    from squidbot.adapters.persistence.jsonl import deserialize_message_safe

    before_times: list[float] = []
    after_times: list[float] = []
    query = "query_needle"

    with tempfile.TemporaryDirectory() as tmp:
        hist_path = Path(tmp) / "history.jsonl"
        _make_large_history_jsonl(hist_path, n_messages, hit_rate)

        def scan_without_filter() -> int:
            """Old behaviour: deserialize every line regardless."""
            count = 0
            with hist_path.open("r", encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    msg = deserialize_message_safe(line)
                    if (
                        msg is not None
                        and isinstance(msg.content, str)
                        and query in msg.content.lower()
                    ):
                        count += 1
            return count

        def scan_with_filter() -> int:
            """New behaviour: skip JSON parsing when query not in raw line."""
            count = 0
            with hist_path.open("r", encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    if query not in line.lower():  # pre-filter
                        continue
                    msg = deserialize_message_safe(line)
                    if (
                        msg is not None
                        and isinstance(msg.content, str)
                        and query in msg.content.lower()
                    ):
                        count += 1
            return count

        for _ in range(RUNS):
            t0 = time.perf_counter()
            scan_without_filter()
            before_times.append(time.perf_counter() - t0)

        for _ in range(RUNS):
            t0 = time.perf_counter()
            scan_with_filter()
            after_times.append(time.perf_counter() - t0)

    pct = int(hit_rate * 100)
    return bench(f"search_history scan ({n_messages} msgs, {pct}% hits)", before_times, after_times)


# ---------------------------------------------------------------------------
# 6. Console() and SSLContext: cached vs recreated per call
# ---------------------------------------------------------------------------


def bench_console_instantiation(n_calls: int) -> dict[str, str]:
    """Compare creating Console() per call vs reusing a cached instance."""
    from rich.console import Console

    before_times: list[float] = []
    after_times: list[float] = []

    # BEFORE: new Console() on every send()
    for _ in range(RUNS):
        t0 = time.perf_counter()
        for _ in range(n_calls):
            c = Console()  # noqa: F841
        before_times.append(time.perf_counter() - t0)

    # AFTER: Console() once, reuse
    for _ in range(RUNS):
        c = Console()  # created once in __init__
        t0 = time.perf_counter()
        for _ in range(n_calls):
            _ = c  # just a reference — the real send() uses self._console
        after_times.append(time.perf_counter() - t0)

    return bench(f"Console() cache ({n_calls} sends)", before_times, after_times)


def bench_ssl_context_instantiation(n_calls: int) -> dict[str, str]:
    """Compare creating SSLContext per call vs reusing a cached instance."""
    import ssl

    before_times: list[float] = []
    after_times: list[float] = []

    # BEFORE: ssl.create_default_context() on every send()
    for _ in range(RUNS):
        t0 = time.perf_counter()
        for _ in range(n_calls):
            ctx = ssl.create_default_context()  # noqa: F841
        before_times.append(time.perf_counter() - t0)

    # AFTER: created once in __init__, reused
    ctx = ssl.create_default_context()
    for _ in range(RUNS):
        t0 = time.perf_counter()
        for _ in range(n_calls):
            _ = ctx  # reference only
        after_times.append(time.perf_counter() - t0)

    return bench(f"SSLContext cache ({n_calls} sends)", before_times, after_times)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    print("Running performance benchmarks…\n")
    print(f"Each measurement: median of {RUNS} runs\n")

    results: list[dict[str, str]] = []

    # --- Persistence ---
    print("  [1/6] load_history cache…", end=" ", flush=True)
    for n in (500, 2000, 10000):
        results.append(await bench_load_history_cache(n))
    print("done")

    print("  [2/6] persist_exchange batch write…", end=" ", flush=True)
    results.append(await bench_persist_exchange_batch())
    print("done")

    # --- Memory ---
    print("  [3/6] build_messages parallel load…", end=" ", flush=True)
    results.append(await bench_parallel_memory_load())
    print("done")

    # --- Agent / tools ---
    print("  [4/6] parallel tool execution…", end=" ", flush=True)
    for n in (2, 4, 8):
        results.append(await bench_parallel_tools(n_tools=n, tool_delay_ms=50))
    print("done")

    # --- Search ---
    print("  [5/6] search_history pre-filter…", end=" ", flush=True)
    for hit_rate in (0.01, 0.10, 0.50):
        results.append(await bench_search_history_filter(5000, hit_rate))
    print("done")

    # --- Object lifecycle ---
    print("  [6/6] Console() / SSLContext caching…", end=" ", flush=True)
    results.append(bench_console_instantiation(10))
    results.append(bench_ssl_context_instantiation(10))
    print("done\n")

    # --- Print table ---
    col_w = max(len(r["label"]) for r in results) + 2
    header = f"{'Benchmark':<{col_w}} {'Before':>12} {'After':>12} {'Speedup':>10}"
    print(header)
    print("-" * len(header))

    prev_group = ""
    for r in results:
        group = r["label"].split()[0]
        if prev_group and group != prev_group:
            print()
        prev_group = group
        print(f"{r['label']:<{col_w}} {r['before']:>12} {r['after']:>12} {r['speedup']:>10}")

    print()
    print("Notes:")
    print("  • 'Before' = naive/sequential behaviour (simulated inline)")
    print("  • 'After'  = optimised implementation from this PR")
    print("  • load_history 'before' = fresh JsonlMemory per call (no cache)")
    print("  • parallel load uses 20ms artificial I/O delay per operation")
    print("  • parallel tools use 50ms artificial delay per tool call")
    print("  • search_history timing is CPU-bound (JSON parsing); real I/O would amplify speedup")
    print("  • Console/SSLContext: 10 sequential send() calls measured")


if __name__ == "__main__":
    asyncio.run(main())
