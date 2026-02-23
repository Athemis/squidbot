"""Tests for JsonlMemory consolidation cursor persistence."""

from __future__ import annotations

from squidbot.adapters.persistence.jsonl import JsonlMemory


async def test_cursor_defaults_to_zero(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    assert await storage.load_consolidated_cursor("sess1") == 0


async def test_cursor_roundtrip(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_consolidated_cursor("sess1", 80)
    assert await storage.load_consolidated_cursor("sess1") == 80


async def test_cursor_isolated_per_session(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_consolidated_cursor("sess1", 10)
    await storage.save_consolidated_cursor("sess2", 20)
    assert await storage.load_consolidated_cursor("sess1") == 10
    assert await storage.load_consolidated_cursor("sess2") == 20


async def test_cursor_file_created_in_sessions_dir(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_consolidated_cursor("sess1", 5)
    meta = tmp_path / "sessions" / "sess1.meta.json"
    assert meta.exists()


async def test_cursor_safe_id_replaces_colons(tmp_path):
    storage = JsonlMemory(base_dir=tmp_path)
    await storage.save_consolidated_cursor("matrix:room123", 3)
    meta = tmp_path / "sessions" / "matrix__room123.meta.json"
    assert meta.exists()
