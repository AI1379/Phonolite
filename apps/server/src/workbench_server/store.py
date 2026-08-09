"""In-memory project state for the Domain API (design doc section 10).

The first vertical slice needs somewhere to keep the imported score, the
versions produced by transforms, and the running ``project.yaml`` config so
that ``inspect`` / ``compare`` / ``render`` / ``record_decision`` can refer to
them by id across requests. This module is that place.

It is deliberately in-memory and single-project: the design doc (section 20)
names SQLite as the right persistence layer, but MVP-1 is a local, single-user
file workflow and a mutable in-memory store keeps the slice end-to-end
runnable without dragging in schema migrations. The public surface
(``get_version`` / ``add_version`` / ``record_decision`` / ...) is small enough
that a SQLite-backed implementation can swap in later without touching routes.

The store is a process-wide singleton accessed through :func:`get_store`;
tests call :meth:`InMemoryProjectStore.reset` (via the ``client`` fixture) so
they stay isolated.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Final

from music_core.ir import ScoreDocument
from music_core.project import (
    Decision,
    GoalRegion,
    MusicalContext,
    ProjectConfig,
    ProjectGoal,
    ProjectSchemaError,
    record_decision,
    set_active_version,
)
from workbench_server.serialization import score_summary_to_dict

_DEFAULT_TITLE: Final[str] = "Untitled Project"


class VersionNotFound(KeyError):
    """Raised when a request references an unknown version id."""

    def __init__(self, version_id: str) -> None:
        super().__init__(version_id)
        self.version_id = version_id

    def __str__(self) -> str:
        return f"version not found: {self.version_id}"


class ArtifactNotFound(KeyError):
    """Raised when an artifact token is unknown or has expired."""

    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.token = token

    def __str__(self) -> str:
        return f"artifact not found: {self.token}"


def _new_project_id() -> str:
    return f"project-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class StoredVersion:
    """A score version held by the store, with provenance for the version tree."""

    version_id: str
    document: ScoreDocument
    parent_id: str | None
    branch: str
    origin: str  # "import" | "transform"
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
    """A render/export product kept in memory and downloadable by token."""

    token: str
    content_type: str
    filename: str
    data: bytes


class InMemoryProjectStore:
    """Holds one project's config, version tree, and generated artifacts."""

    def __init__(self) -> None:
        self._config: ProjectConfig | None = None
        self._versions: dict[str, StoredVersion] = {}
        self._artifacts: dict[str, ArtifactRecord] = {}

    # -- lifecycle --------------------------------------------------------- #
    def reset(self) -> None:
        """Clear all state. Called by the test fixture before each test."""
        self._config = None
        self._versions = {}
        self._artifacts = {}

    # -- config ------------------------------------------------------------ #
    @property
    def config(self) -> ProjectConfig:
        """The project config, creating a default one on first access."""
        if self._config is None:
            self._config = ProjectConfig(id=_new_project_id(), title=_DEFAULT_TITLE)
        return self._config

    def ensure_project(self, *, project_id: str | None, title: str | None) -> ProjectConfig:
        """Initialise the project if needed, applying any id/title overrides.

        Once a project exists we keep its id stable (it is the anchor
        ``project.yaml`` identity), so later calls only update the title.
        """
        if self._config is None:
            self._config = ProjectConfig(
                id=project_id or _new_project_id(),
                title=title or _DEFAULT_TITLE,
            )
        elif title is not None:
            self._config = replace(self._config, title=title)
        return self._config

    def update_musical_context(self, context: MusicalContext) -> ProjectConfig:
        self._config = replace(self.config, musical_context=context)
        return self._config

    # -- versions ---------------------------------------------------------- #
    def add_version(
        self,
        document: ScoreDocument,
        *,
        parent_id: str | None,
        branch: str,
        origin: str,
        description: str,
    ) -> StoredVersion:
        """Register a new version keyed by its (already-minted) document id."""
        version = StoredVersion(
            version_id=document.id,
            document=document,
            parent_id=parent_id,
            branch=branch,
            origin=origin,
            created_at=_now_iso(),
            description=description,
        )
        self._versions[version.version_id] = version
        return version

    def get_version(self, version_id: str) -> StoredVersion:
        """Return a version or raise :class:`VersionNotFound`."""
        version = self._versions.get(version_id)
        if version is None:
            raise VersionNotFound(version_id)
        return version

    def has_version(self, version_id: str) -> bool:
        return version_id in self._versions

    def list_versions(self) -> list[StoredVersion]:
        """Versions in insertion order (oldest import first)."""
        return list(self._versions.values())

    def active_version_id(self) -> str | None:
        return self.config.active_version

    # -- project mutations ------------------------------------------------- #
    def update_goal(
        self,
        description: str,
        bars: tuple[int, int] | None,
        beats: tuple[float, float] | None,
    ) -> ProjectConfig:
        region = GoalRegion(bars=bars, beats=beats) if (bars is not None or beats is not None) else None
        goal = ProjectGoal(description=description, region=region)
        self._config = replace(self.config, current_goal=goal)
        return self._config

    def record_decision(
        self,
        *,
        summary: str,
        chosen_version_id: str | None = None,
        reason: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> tuple[ProjectConfig, Decision]:
        """Append a decision immutably via ``music_core.project``."""
        self._config, decision = record_decision(
            self.config,
            summary=summary,
            chosen_version_id=chosen_version_id,
            reason=reason,
            tags=tags,
        )
        return self._config, decision

    def accept_variant(self, version_id: str) -> ProjectConfig:
        """Promote ``version_id`` to active; the version must already exist."""
        if not self.has_version(version_id):
            raise VersionNotFound(version_id)
        self._config = set_active_version(self.config, version_id)
        return self._config

    # -- artifacts --------------------------------------------------------- #
    def store_artifact(
        self, *, content_type: str, filename: str, data: bytes
    ) -> ArtifactRecord:
        token = uuid.uuid4().hex
        record = ArtifactRecord(
            token=token, content_type=content_type, filename=filename, data=data
        )
        self._artifacts[token] = record
        return record

    def get_artifact(self, token: str) -> ArtifactRecord:
        record = self._artifacts.get(token)
        if record is None:
            raise ArtifactNotFound(token)
        return record


_STORE = InMemoryProjectStore()


def get_store() -> InMemoryProjectStore:
    """Process-wide singleton; tests reset it through the ``client`` fixture."""
    return _STORE


def decode_midi_b64(midi_b64: str) -> bytes:
    """Decode base64 MIDI bytes, raising ``ValueError`` on malformed input."""
    try:
        return base64.b64decode(midi_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"invalid base64 MIDI payload: {exc}") from exc


__all__ = [
    "ArtifactNotFound",
    "ArtifactRecord",
    "InMemoryProjectStore",
    "ProjectSchemaError",
    "StoredVersion",
    "VersionNotFound",
    "decode_midi_b64",
    "get_store",
]
