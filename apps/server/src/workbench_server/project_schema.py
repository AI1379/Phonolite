"""Transactional migration from the single-project store to a project catalog."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import cast

from music_core.project import ProjectConfig, dumps_project, loads_project


def migrate_projects(connection: sqlite3.Connection) -> None:
    """Assign all legacy material to its original project without changing IDs."""
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TABLE IF NOT EXISTS wb_schema (version INTEGER NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS wb_agent_sessions (session_id TEXT PRIMARY KEY, project_id TEXT NOT NULL)")
        row = connection.execute("SELECT version FROM wb_schema").fetchone()
        if row is not None:
            if row[0] != 2:
                raise RuntimeError("Unsupported Workbench database schema version")
            return
        for statement in (
            "CREATE TABLE IF NOT EXISTS wb_projects (id TEXT PRIMARY KEY, yaml TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS wb_workspace (singleton INTEGER PRIMARY KEY CHECK(singleton=1), active_project_id TEXT)",
            "CREATE TABLE IF NOT EXISTS wb_versions (id TEXT PRIMARY KEY, document BLOB NOT NULL, parent_id TEXT, branch TEXT NOT NULL, origin TEXT NOT NULL, created_at TEXT NOT NULL, description TEXT NOT NULL, project_id TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS wb_artifacts (token TEXT PRIMARY KEY, content_type TEXT NOT NULL, filename TEXT NOT NULL, data BLOB NOT NULL, project_id TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS wb_project_references (project_id TEXT NOT NULL, id TEXT NOT NULL, document BLOB NOT NULL, PRIMARY KEY(project_id,id))",
        ):
            connection.execute(statement)
        for table in ("wb_versions", "wb_artifacts"):
            columns = {cast(str, item[1]) for item in connection.execute(f"PRAGMA table_info({table})")}
            if "project_id" not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN project_id TEXT")
        tables = {cast(str, item[0]) for item in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        legacy = connection.execute("SELECT yaml FROM wb_project WHERE singleton=1").fetchone() if "wb_project" in tables else None
        has_material = any(connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None
                           for table in ("wb_versions", "wb_artifacts", "wb_references") if table in tables)
        if legacy is not None or has_material:
            config = loads_project(cast(str, legacy[0])) if legacy is not None else ProjectConfig(f"project-{uuid.uuid4().hex[:12]}", "Recovered Project")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            connection.execute("INSERT INTO wb_projects VALUES (?, ?, ?, ?)", (config.id, dumps_project(config), now, now))
            connection.execute("UPDATE wb_versions SET project_id=? WHERE project_id IS NULL", (config.id,))
            connection.execute("UPDATE wb_artifacts SET project_id=? WHERE project_id IS NULL", (config.id,))
            if "wb_references" in tables:
                connection.execute("INSERT INTO wb_project_references SELECT ?, id, document FROM wb_references", (config.id,))
            connection.execute("INSERT OR REPLACE INTO wb_workspace VALUES (1, ?)", (config.id,))
        for table in ("wb_versions", "wb_artifacts"):
            connection.execute(f"CREATE INDEX IF NOT EXISTS {table}_project ON {table}(project_id)")
        connection.execute("INSERT INTO wb_schema VALUES (2)")
