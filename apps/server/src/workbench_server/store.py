"""Shared store records and lazy lifecycle for durable SQLite project storage."""

from __future__ import annotations

import base64
import binascii
import os
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Generator
from pathlib import Path
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workbench_server.persistence import SQLiteProjectStore

from music_core.ir import ScoreDocument
from music_core.project import ProjectSchemaError
from workbench_server.serialization import score_summary_to_dict


class VersionNotFound(KeyError):
    """Raised when a request references an unknown version id."""

    def __init__(self, version_id: str) -> None:
        super().__init__(version_id)
        self.version_id = version_id

    def __str__(self) -> str:
        return f"version not found: {self.version_id}"


class ProjectNotFound(KeyError):
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__(project_id)

    def __str__(self) -> str:
        return f"project not found: {self.project_id}"


class ArtifactNotFound(KeyError):
    """Raised when an artifact token is unknown or has expired."""

    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.token = token

    def __str__(self) -> str:
        return f"artifact not found: {self.token}"


@dataclass(frozen=True)
class StoredVersion:
    """A score version held by the store, with provenance for the version tree."""

    version_id: str
    document: ScoreDocument
    parent_id: str | None
    branch: str
    origin: str  # "import" | "transform" | "draft" | "edit"
    created_at: str
    description: str

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            **score_summary_to_dict(self.document),
            "version_id": self.version_id,
            "parent_id": self.parent_id,
            "branch": self.branch,
            "origin": self.origin,
            "created_at": self.created_at,
            "description": self.description,
        }
        return out


@dataclass(frozen=True)
class ArtifactRecord:
    """A persisted render/export product downloadable by its stable token."""

    token: str
    content_type: str
    filename: str
    data: bytes


_project_store: SQLiteProjectStore | None = None
_request_project: ContextVar[str | None] = ContextVar("workbench_project", default=None)


def get_workspace_store() -> SQLiteProjectStore:
    """Lazily open the durable project store; tests configure an isolated path."""
    global _project_store
    if _project_store is None:
        from workbench_server.persistence import SQLiteProjectStore
        _project_store = SQLiteProjectStore(os.environ.get("WORKBENCH_DB_PATH", str(Path.cwd() / "project.db")))
    return _project_store


def get_store() -> SQLiteProjectStore:
    """Bind each request to its captured project, even if the workspace switches."""
    workspace = get_workspace_store()
    project_id = _request_project.get()
    return workspace.for_project(project_id) if project_id is not None else workspace


@contextmanager
def project_scope(project_id: str | None) -> Generator[None, None, None]:
    token = _request_project.set(project_id)
    try:
        yield
    finally:
        _request_project.reset(token)


def request_project_id() -> str | None:
    return _request_project.get()


def configure_project_store(path: str | Path) -> SQLiteProjectStore:
    global _project_store
    from workbench_server.persistence import SQLiteProjectStore
    if _project_store is not None:
        _project_store.close()
    _project_store = SQLiteProjectStore(path)
    return _project_store


def close_project_store() -> None:
    global _project_store
    if _project_store is not None:
        _project_store.close()
    _project_store = None


def decode_midi_b64(midi_b64: str) -> bytes:
    """Decode base64 MIDI bytes, raising ``ValueError`` on malformed input."""
    try:
        return base64.b64decode(midi_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"invalid base64 MIDI payload: {exc}") from exc


__all__ = [
    "ArtifactNotFound",
    "ArtifactRecord",
    "ProjectSchemaError",
    "StoredVersion",
    "VersionNotFound",
    "decode_midi_b64",
    "get_store",
    "configure_project_store",
    "close_project_store",
]
