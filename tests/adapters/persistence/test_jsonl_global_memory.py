"""Tests for JsonlMemory global memory and session summary persistence."""

from __future__ import annotations

from squidbot.adapters.persistence.jsonl import JsonlMemory


async def test_global_memory_default_empty(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    assert await storage.load_global_memory() == ""


async def test_global_memory_roundtrip(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_global_memory("User likes Python.")
    assert await storage.load_global_memory() == "User likes Python."


async def test_global_memory_file_location(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_global_memory("facts")
    assert (tmp_path / "workspace" / "MEMORY.md").exists()


async def test_session_summary_default_empty(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    assert await storage.load_session_summary("sess1") == ""


async def test_session_summary_roundtrip(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_session_summary("sess1", "Summary text.")
    assert await storage.load_session_summary("sess1") == "Summary text."


async def test_session_summary_file_location(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_session_summary("sess1", "text")
    assert (tmp_path / "memory" / "sess1" / "summary.md").exists()


async def test_session_summary_safe_id(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_session_summary("matrix:room1", "text")
    assert (tmp_path / "memory" / "matrix__room1" / "summary.md").exists()
