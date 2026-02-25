"""Deterministic local performance baseline runner.

This script benchmarks a small set of hot-path operations using synthetic fixtures
created in temporary directories. It prints stable key=value lines for easy diffing
and also writes the same output to .sisyphus/evidence/task-1-baseline.txt.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from squidbot.adapters.persistence.jsonl import JsonlMemory
from squidbot.adapters.skills.fs import FsSkillsLoader

HISTORY_SIZES: tuple[int, ...] = (1_000, 10_000, 50_000)
HISTORY_LAST_N = 80
HISTORY_REPEATS = 5
SKILL_COUNT = 400
SKILLS_REPEATS = 10
EVIDENCE_PATH = Path(".sisyphus/evidence/task-1-baseline.txt")


def _build_message_line(index: int) -> str:
    payload = {
        "role": "user" if index % 2 == 0 else "assistant",
        "content": f"Synthetic message {index:05d}",
        "timestamp": f"2026-01-01T00:00:{index % 60:02d}",
        "channel": "cli:perf",
        "sender_id": "perf-user",
    }
    return json.dumps(payload) + "\n"


def _write_history_fixture(base_dir: Path, message_count: int) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    history_path = base_dir / "history.jsonl"
    with history_path.open("w", encoding="utf-8") as handle:
        for index in range(message_count):
            handle.write(_build_message_line(index))


def _write_skill_file(path: Path, skill_name: str, body_suffix: str) -> None:
    text = (
        "---\n"
        f"name: {skill_name}\n"
        f"description: Synthetic skill {skill_name}\n"
        "always: false\n"
        "metadata:\n"
        "  squidbot:\n"
        "    emoji: ':gear:'\n"
        "---\n\n"
        f"# {skill_name}\n\n"
        f"This is {skill_name}. {body_suffix}\n"
    )
    path.write_text(text, encoding="utf-8")


def _build_skills_fixture(root: Path) -> tuple[Path, Path, str]:
    high_priority = root / "skills_high"
    low_priority = root / "skills_low"
    high_priority.mkdir(parents=True, exist_ok=True)
    low_priority.mkdir(parents=True, exist_ok=True)

    for index in range(SKILL_COUNT):
        name = f"skill_{index:04d}"
        low_skill_dir = low_priority / name
        low_skill_dir.mkdir(parents=True, exist_ok=True)
        _write_skill_file(low_skill_dir / "SKILL.md", name, "Baseline body from low priority dir.")

    for index in range(50):
        name = f"skill_{index:04d}"
        high_skill_dir = high_priority / name
        high_skill_dir.mkdir(parents=True, exist_ok=True)
        _write_skill_file(
            high_skill_dir / "SKILL.md", name, "Override body from high priority dir."
        )

    return high_priority, low_priority, "skill_0007"


async def _measure_history_load_ms(message_count: int) -> float:
    with TemporaryDirectory() as temp_dir:
        base_dir = Path(temp_dir) / f"history_{message_count}"
        _write_history_fixture(base_dir, message_count)
        memory = JsonlMemory(base_dir)

        await memory.load_history(last_n=HISTORY_LAST_N)
        samples_ms: list[float] = []
        for _ in range(HISTORY_REPEATS):
            start = perf_counter()
            await memory.load_history(last_n=HISTORY_LAST_N)
            samples_ms.append((perf_counter() - start) * 1000.0)

    return median(samples_ms)


def _measure_sync_call_ms(function: Callable[[], object], repeats: int) -> float:
    function()
    samples_ms: list[float] = []
    for _ in range(repeats):
        start = perf_counter()
        function()
        samples_ms.append((perf_counter() - start) * 1000.0)
    return median(samples_ms)


def _measure_skills_metrics() -> tuple[float, float]:
    with TemporaryDirectory() as temp_dir:
        high_priority, low_priority, sample_skill = _build_skills_fixture(Path(temp_dir))
        loader = FsSkillsLoader([high_priority, low_priority])

        list_ms = _measure_sync_call_ms(loader.list_skills, SKILLS_REPEATS)
        body_ms = _measure_sync_call_ms(
            lambda: loader.load_skill_body(sample_skill), SKILLS_REPEATS
        )
    return list_ms, body_ms


async def _collect_metrics() -> list[tuple[str, float]]:
    history_metrics: list[tuple[str, float]] = []
    for size in HISTORY_SIZES:
        value = await _measure_history_load_ms(size)
        history_metrics.append((f"history_load_{size // 1000}k_ms", value))

    skills_list_ms, skills_body_ms = _measure_skills_metrics()
    return [
        *history_metrics,
        ("skills_list_ms", skills_list_ms),
        ("skill_body_load_ms", skills_body_ms),
    ]


def _render_lines(metrics: list[tuple[str, float]]) -> list[str]:
    return [f"{key}={value:.3f}" for key, value in metrics]


def _write_evidence(lines: list[str]) -> None:
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    metrics = asyncio.run(_collect_metrics())
    lines = _render_lines(metrics)
    for line in lines:
        print(line)
    _write_evidence(lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
