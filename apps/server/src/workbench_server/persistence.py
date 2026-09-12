"""Project-scoped SQLite storage with immutable score versions and durable assets.

Tables use the wb_ prefix to coexist with memory-core's independent event ledger.
Full IR JSON retains stable IDs, annotations and performance data; MIDI is only
an interchange artifact. Each mutation commits before its API response returns.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from pydantic import TypeAdapter
from music_core.ir import ScoreDocument
from music_core.project import (
    Decision, GoalRegion, MusicalContext, ProjectConfig, ProjectGoal,
    dumps_project, loads_project, record_decision, set_active_version,
)
from music_core.reference import AlignmentAnchor, ScoreReference
from workbench_server.assets import PreparedReference, ReferenceRecord
from workbench_server.store import ArtifactNotFound, ArtifactRecord, ProjectNotFound, StoredVersion, VersionNotFound
from workbench_server.project_schema import migrate_projects

_SCORE = TypeAdapter(ScoreDocument)
_REFERENCE = TypeAdapter(ReferenceRecord)


class SQLiteProjectStore:
    """Project catalog and bound project views sharing one locked SQLite connection."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._bound_project_id: str | None = None
        migrate_projects(self._db)

    def for_project(self, project_id: str) -> SQLiteProjectStore:
        self.project_config(project_id)
        view = object.__new__(SQLiteProjectStore)
        view.path, view._db, view._lock = self.path, self._db, self._lock
        view._bound_project_id = project_id
        return view

    def active_project_id(self) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT active_project_id FROM wb_workspace WHERE singleton=1").fetchone()
            return cast(str | None, row[0]) if row is not None else None

    @property
    def project_id(self) -> str:
        project_id = self._bound_project_id or self.active_project_id()
        return project_id if project_id is not None else self.create_project("Untitled Project").id

    def project_config(self, project_id: str) -> ProjectConfig:
        with self._lock:
            row = self._db.execute("SELECT yaml FROM wb_projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise ProjectNotFound(project_id)
        return loads_project(cast(str, row[0]))

    def create_project(self, title: str, *, workflow: str = "composition", project_id: str | None = None) -> ProjectConfig:
        title = title.strip()
        if not title or len(title) > 160 or workflow not in ("composition", "transcription"):
            raise ValueError("project needs a title of 1..160 characters and a supported workflow")
        config = ProjectConfig(project_id or f"project-{uuid.uuid4().hex[:12]}", title, extra={"workflow": workflow})
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._db:
            self._db.execute("INSERT INTO wb_projects VALUES (?, ?, ?, ?)", (config.id, dumps_project(config), now, now))
            self._db.execute("INSERT INTO wb_workspace VALUES (1, ?) ON CONFLICT(singleton) DO UPDATE SET active_project_id=excluded.active_project_id", (config.id,))
        return config

    def open_project(self, project_id: str) -> ProjectConfig:
        config = self.project_config(project_id)
        with self._lock, self._db:
            self._db.execute("INSERT INTO wb_workspace VALUES (1, ?) ON CONFLICT(singleton) DO UPDATE SET active_project_id=excluded.active_project_id", (project_id,))
        return config

    def rename_project(self, project_id: str, title: str) -> ProjectConfig:
        if not title.strip() or len(title.strip()) > 160:
            raise ValueError("project title must have 1..160 characters")
        with self._lock, self._db:
            config = replace(self.project_config(project_id), title=title.strip())
            self._save_config(config)
            return config

    def list_projects(self) -> list[dict[str, object]]:
        with self._lock:
            result: list[dict[str, object]] = []
            for row in self._db.execute("SELECT * FROM wb_projects ORDER BY updated_at DESC, rowid DESC").fetchall():
                config = loads_project(cast(str, row["yaml"]))
                workflow = config.extra.get("workflow")
                result.append({"id": config.id, "title": config.title, "workflow": workflow if workflow in ("composition", "transcription") else "existing",
                               "active_version": config.active_version, "working_version": config.extra.get("working_version"),
                               "version_count": self._db.execute("SELECT COUNT(*) FROM wb_versions WHERE project_id=?", (config.id,)).fetchone()[0],
                               "reference_count": self._db.execute("SELECT COUNT(*) FROM wb_project_references WHERE project_id=?", (config.id,)).fetchone()[0],
                               "created_at": row["created_at"], "updated_at": row["updated_at"]})
            return result

    def session_project(self, session_id: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT project_id FROM wb_agent_sessions WHERE session_id=?", (session_id,)).fetchone()
            return cast(str, row[0]) if row is not None else None

    def bind_session(self, session_id: str, project_id: str) -> None:
        self.project_config(project_id)
        with self._lock, self._db:
            self._db.execute("INSERT INTO wb_agent_sessions VALUES (?, ?) ON CONFLICT(session_id) DO NOTHING", (session_id, project_id))
            if self.session_project(session_id) != project_id:
                raise ValueError("Agent session belongs to another project")

    def close(self) -> None:
        if self._bound_project_id is not None:
            return
        with self._lock:
            self._db.close()

    def _save_config(self, config: ProjectConfig) -> None:
        self._db.execute("UPDATE wb_projects SET yaml=?, updated_at=? WHERE id=?",
                         (dumps_project(config), datetime.now(timezone.utc).isoformat(timespec="seconds"), config.id))

    @property
    def config(self) -> ProjectConfig:
        with self._lock:
            return self.project_config(self.project_id)

    def ensure_project(self, *, project_id: str | None, title: str | None) -> ProjectConfig:
        with self._lock:
            current = self._bound_project_id or self.active_project_id()
            if current is None:
                return self.create_project(title or "Untitled Project", project_id=project_id)
            if project_id is not None and project_id != current:
                raise ValueError("import project_id differs from the request's selected project")
            # A material's filename/title must never rename an existing project.
            return self.project_config(current)

    def restore_config(self, config: ProjectConfig) -> None:
        """Restore an explicitly supplied legacy snapshot after its versions exist."""
        if config.id != self.project_id:
            raise ValueError("config belongs to another project")
        if config.active_version is not None and not self.has_version(config.active_version):
            raise VersionNotFound(config.active_version)
        with self._lock, self._db:
            self._save_config(config)

    def update_musical_context(self, context: MusicalContext) -> ProjectConfig:
        with self._lock:
            config = replace(self.config, musical_context=context)
            with self._db:
                self._save_config(config)
            return config

    def add_version(self, document: ScoreDocument, *, parent_id: str | None, branch: str,
                    origin: str, description: str, created_at: str | None = None) -> StoredVersion:
        project_id = self.project_id
        if parent_id is not None and not self.has_version(parent_id):
            raise VersionNotFound(parent_id)
        if document.reference is not None:
            self.get_reference(document.reference.asset_id)
        timestamp = created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._db:
            self._db.execute("INSERT INTO wb_versions (id, document, parent_id, branch, origin, created_at, description, project_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (document.id, _SCORE.dump_json(document), parent_id, branch, origin, timestamp, description, project_id))
        return StoredVersion(document.id, document, parent_id, branch, origin, timestamp, description)

    @staticmethod
    def _version(row: sqlite3.Row) -> StoredVersion:
        return StoredVersion(cast(str, row["id"]), _SCORE.validate_json(cast(bytes, row["document"])),
                             cast(str | None, row["parent_id"]), cast(str, row["branch"]),
                             cast(str, row["origin"]), cast(str, row["created_at"]), cast(str, row["description"]))

    def get_version(self, version_id: str) -> StoredVersion:
        with self._lock:
            row = self._db.execute("SELECT * FROM wb_versions WHERE id=? AND project_id=?", (version_id, self.project_id)).fetchone()
        if row is None:
            raise VersionNotFound(version_id)
        return self._version(row)

    def has_version(self, version_id: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM wb_versions WHERE id=? AND project_id=?", (version_id, self.project_id)).fetchone() is not None

    def list_versions(self) -> list[StoredVersion]:
        with self._lock:
            return [self._version(row) for row in self._db.execute("SELECT * FROM wb_versions WHERE project_id=? ORDER BY rowid", (self.project_id,)).fetchall()]

    def active_version_id(self) -> str | None:
        return self.config.active_version

    def set_working_version(self, version_id: str) -> None:
        if not self.has_version(version_id):
            raise VersionNotFound(version_id)
        with self._lock:
            config = self.config
            updated = replace(config, extra={**config.extra, "working_version": version_id})
            with self._db:
                self._save_config(updated)

    def update_goal(self, description: str, bars: tuple[int, int] | None, beats: tuple[float, float] | None) -> ProjectConfig:
        with self._lock:
            goal = ProjectGoal(description, GoalRegion(bars, beats) if bars is not None or beats is not None else None)
            config = replace(self.config, current_goal=goal)
            with self._db:
                self._save_config(config)
            return config

    def record_decision(self, *, summary: str, chosen_version_id: str | None = None,
                        reason: str | None = None, tags: tuple[str, ...] = ()) -> tuple[ProjectConfig, Decision]:
        with self._lock:
            config, decision = record_decision(self.config, summary=summary, chosen_version_id=chosen_version_id, reason=reason, tags=tags)
            with self._db:
                self._save_config(config)
            return config, decision

    def accept_variant(self, version_id: str) -> ProjectConfig:
        with self._lock:
            if not self.has_version(version_id):
                raise VersionNotFound(version_id)
            config = set_active_version(self.config, version_id)
            with self._db:
                self._save_config(config)
            return config

    def _insert_artifact(self, record: ArtifactRecord, project_id: str) -> None:
        self._db.execute("INSERT INTO wb_artifacts (token, content_type, filename, data, project_id) VALUES (?, ?, ?, ?, ?)",
                         (record.token, record.content_type, record.filename, record.data, project_id))

    def store_artifact(self, *, content_type: str, filename: str, data: bytes) -> ArtifactRecord:
        record = ArtifactRecord(uuid.uuid4().hex, content_type, filename, data)
        project_id = self.project_id
        with self._lock, self._db:
            self._insert_artifact(record, project_id)
        return record

    def get_artifact(self, token: str) -> ArtifactRecord:
        with self._lock:
            row = self._db.execute("SELECT * FROM wb_artifacts WHERE token=? AND project_id=?", (token, self.project_id)).fetchone()
        if row is None:
            raise ArtifactNotFound(token)
        return ArtifactRecord(token, cast(str, row["content_type"]), cast(str, row["filename"]), cast(bytes, row["data"]))

    def add_reference(self, audio: PreparedReference) -> ReferenceRecord:
        asset_id = "ref-" + audio.sha256
        project_id = self.project_id
        with self._lock, self._db:
            row = self._db.execute("SELECT document FROM wb_project_references WHERE id=? AND project_id=?", (asset_id, project_id)).fetchone()
            if row is not None:
                return _REFERENCE.validate_json(cast(bytes, row[0]))
            original = ArtifactRecord(uuid.uuid4().hex, "application/octet-stream", audio.filename, audio.original)
            playback = ArtifactRecord(uuid.uuid4().hex, "audio/wav", "reference-preview.wav", audio.playback) if audio.playback is not None else None
            video = ArtifactRecord(uuid.uuid4().hex, "video/mp4", "reference-preview.mp4", audio.video) if audio.video is not None else None
            record = ReferenceRecord(asset_id, audio.filename, audio.sha256, audio.duration_seconds,
                                     audio.sample_rate, audio.channels, original.token, playback.token if playback else None, audio.peaks,
                                     media_kind=audio.media_kind, video_token=video.token if video else None,
                                     video_width=audio.video_width, video_height=audio.video_height,
                                     has_audio=audio.has_audio, warnings=audio.warnings)
            self._insert_artifact(original, project_id)
            if playback is not None:
                self._insert_artifact(playback, project_id)
            if video is not None:
                self._insert_artifact(video, project_id)
            self._db.execute("INSERT INTO wb_project_references VALUES (?, ?, ?)", (project_id, asset_id, _REFERENCE.dump_json(record)))
            return record

    def get_reference(self, asset_id: str) -> ReferenceRecord:
        with self._lock:
            row = self._db.execute("SELECT document FROM wb_project_references WHERE id=? AND project_id=?", (asset_id, self.project_id)).fetchone()
        if row is None:
            raise ValueError("reference audio not found")
        return _REFERENCE.validate_json(cast(bytes, row[0]))

    def list_references(self) -> list[ReferenceRecord]:
        with self._lock:
            return [_REFERENCE.validate_json(cast(bytes, row[0])) for row in self._db.execute("SELECT document FROM wb_project_references WHERE project_id=? ORDER BY rowid", (self.project_id,)).fetchall()]

    def update_alignment(self, asset_id: str, anchors: tuple[AlignmentAnchor, ...]) -> ReferenceRecord:
        ScoreReference(asset_id, anchors)
        with self._lock:
            record = self.get_reference(asset_id)
            if anchors[-1].seconds > record.duration_seconds:
                raise ValueError("alignment extends beyond the reference audio")
            result = replace(record, anchors=anchors)
            with self._db:
                self._db.execute("UPDATE wb_project_references SET document=? WHERE id=? AND project_id=?", (_REFERENCE.dump_json(result), asset_id, self.project_id))
            return result
