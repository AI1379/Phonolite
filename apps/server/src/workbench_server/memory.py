"""Application-owned lifecycle for the persistent memory-core database."""

from __future__ import annotations

import os
from pathlib import Path

from memory_core import SQLiteMemoryStore

_memory_store: SQLiteMemoryStore | None = None


class MemoryRecordNotFound(KeyError):
    """Raised when an API command references an unknown memory record."""

    def __init__(self, record_id: str) -> None:
        super().__init__(record_id)
        self.record_id = record_id

    def __str__(self) -> str:
        return f"memory record not found: {self.record_id}"


def _default_database_path() -> Path:
    configured = os.environ.get("WORKBENCH_DB_PATH")
    return Path(configured) if configured else Path.cwd() / "project.db"


def get_memory_store() -> SQLiteMemoryStore:
    """Return the process-wide persistent memory store, creating it lazily."""
    global _memory_store
    if _memory_store is None:
        _memory_store = SQLiteMemoryStore(_default_database_path())
    return _memory_store


def configure_memory_store(path: str | Path) -> SQLiteMemoryStore:
    """Replace the process store; tests use this to isolate their databases."""
    global _memory_store
    if _memory_store is not None:
        _memory_store.close()
    _memory_store = SQLiteMemoryStore(path)
    return _memory_store


__all__ = ["MemoryRecordNotFound", "configure_memory_store", "get_memory_store"]
