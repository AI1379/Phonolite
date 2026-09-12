"""Independent project workspaces, legacy migration and in-flight request binding."""

from __future__ import annotations

import base64
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import threading
import wave

from fastapi.testclient import TestClient
from pydantic import TypeAdapter
import pytest

from music_core.edit import create_draft
from music_core.ir import ScoreDocument
from music_core.project import ProjectConfig, dumps_project
from workbench_server.assets import PreparedReference, prepare_audio
from workbench_server.persistence import SQLiteProjectStore
from workbench_server.store import ArtifactNotFound, VersionNotFound, configure_project_store, get_store


def _audio() -> str:
    stream = BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
        wav.writeframes(bytes(4 * 8000 * 2))
    return base64.b64encode(stream.getvalue()).decode()


def _new(client: TestClient, name: str) -> str:
    result = client.post("/api/projects", json={"title": name, "workflow": "transcription"})
    assert result.status_code == 201, result.text
    return result.json()["result"]["project"]["id"]


def test_catalog_starts_empty_and_create_open_rename_restore(client: TestClient) -> None:
    assert client.get("/api/projects").json()["result"] == {"projects": [], "active_project_id": None}
    a, b = _new(client, "First piece"), _new(client, "Second piece")
    assert client.get("/api/project").json()["result"]["project"]["id"] == b
    assert client.post(f"/api/projects/{a}/open").status_code == 200
    assert client.patch(f"/api/projects/{a}", json={"title": "Piano arrangement"}).status_code == 200
    configure_project_store(get_store().path)
    catalog = client.get("/api/projects").json()["result"]
    assert catalog["active_project_id"] == a
    assert {item["title"] for item in catalog["projects"]} == {"Piano arrangement", "Second piece"}
    assert client.get("/api/project").json()["result"]["versions"] == []
    assert client.post("/api/projects", json={"title": "   "}).status_code == 422
    assert client.post("/api/projects/missing/open").status_code == 404


def test_switch_isolates_scores_goals_decisions_references_and_artifacts(client: TestClient, make_piano_b64: Callable[..., str]) -> None:
    a = _new(client, "A's title")
    a_headers = {"X-Workbench-Project": a}
    imported = client.post("/api/score/import", json={"midi_b64": make_piano_b64(), "title": "source-file-name"}).json()["result"]["version"]["version_id"]
    assert client.get("/api/project").json()["result"]["project"]["title"] == "A's title"
    client.patch("/api/project/goal", json={"description": "Keep the melody"})
    client.post("/api/project/choose", json={"chosen_version_id": imported, "reason": "Original phrasing"})
    token = client.post(f"/api/score/{imported}/export").json()["result"]["artifact_token"]
    reference = client.post("/api/references/import", json={"filename": "source.wav", "audio_b64": _audio()}).json()["result"]["reference"]
    b = _new(client, "B")
    status = client.get("/api/project").json()["result"]
    assert status["versions"] == [] and status["active_version"] is None
    assert "current_goal" not in status["project"] and "decisions" not in status["project"]
    assert client.get("/api/references").json()["result"]["references"] == []
    assert client.get(f"/api/score/{imported}").status_code == 404
    assert client.get(f"/api/artifact/{token}").status_code == 404
    assert client.post("/api/project/accept", json={"version_id": imported}).status_code == 404
    assert client.post("/api/project/decision", json={"summary":"wrong project", "chosen_version_id":imported}).status_code == 404
    assert client.post("/api/score/draft", json={"reference_id": reference["id"]}).status_code == 422
    assert client.get(f"/api/artifact/{token}", params={"project_id": a}).status_code == 200
    # A pinned client remains on A after the workspace's default changes to B.
    assert client.get("/api/project", headers=a_headers).json()["result"]["project"]["id"] == a
    assert client.get("/api/projects").json()["result"]["active_project_id"] == b
    restored = client.post(f"/api/projects/{a}/open").json()["result"]["project"]
    assert restored["current_goal"]["description"] == "Keep the melody"
    assert len(restored["decisions"]) == 1


def test_same_reference_file_has_independent_alignment_per_project(client: TestClient) -> None:
    a = _new(client, "A")
    payload = {"filename": "same.wav", "audio_b64": _audio()}
    first = client.post("/api/references/import", json=payload).json()["result"]["reference"]
    anchors_a = [{"seconds": 1, "beat": 0}, {"seconds": 3, "beat": 4}]
    client.put(f"/api/references/{first['id']}/alignment", json={"anchors": anchors_a})
    _new(client, "B")
    second = client.post("/api/references/import", json=payload).json()["result"]["reference"]
    assert first["id"] == second["id"]
    assert first["original_token"] != second["original_token"]
    assert second["anchors"] == []
    client.put(f"/api/references/{second['id']}/alignment", json={"anchors": [{"seconds": 0, "beat": 0}, {"seconds": 2, "beat": 8}]})
    restored = client.get("/api/references", headers={"X-Workbench-Project": a}).json()["result"]["references"][0]
    assert restored["anchors"] == anchors_a


def test_inflight_import_stays_in_original_project(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    a = _new(client, "A")
    started, release = threading.Event(), threading.Event()
    def delayed(data: bytes, filename: str) -> PreparedReference:
        started.set()
        assert release.wait(timeout=5)
        return prepare_audio(data, filename)
    monkeypatch.setattr("workbench_server.transcription.prepare_audio", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/api/references/import", json={"filename": "slow.wav", "audio_b64": _audio()})
        try:
            assert started.wait(timeout=5)
            _new(client, "B")
        finally:
            release.set()
        assert future.result(timeout=5).status_code == 200
    assert client.get("/api/references").json()["result"]["references"] == []
    assert len(client.get("/api/references", headers={"X-Workbench-Project": a}).json()["result"]["references"]) == 1


def test_legacy_database_migration_preserves_ids_bytes_and_project(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    doc = create_draft(title="legacy")
    config = ProjectConfig("legacy-id", "Legacy piece", active_version=doc.id, extra={"working_version": doc.id})
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE wb_project (singleton INTEGER PRIMARY KEY, yaml TEXT NOT NULL);
            CREATE TABLE wb_versions (id TEXT PRIMARY KEY, document BLOB, parent_id TEXT, branch TEXT, origin TEXT, created_at TEXT, description TEXT);
            CREATE TABLE wb_artifacts (token TEXT PRIMARY KEY, content_type TEXT, filename TEXT, data BLOB);
            CREATE TABLE wb_references (id TEXT PRIMARY KEY, document BLOB);
        """)
        connection.execute("INSERT INTO wb_project VALUES (1,?)", (dumps_project(config),))
        connection.execute("INSERT INTO wb_versions VALUES (?,?,NULL,'draft','draft','old-time','draft')", (doc.id, TypeAdapter(ScoreDocument).dump_json(doc)))
        connection.execute("INSERT INTO wb_artifacts VALUES ('original','audio/wav','source.wav',?)", (b"source bytes",))
        connection.execute("INSERT INTO wb_references VALUES ('reference',?)", (json.dumps({"id":"reference","filename":"source.wav","sha256":"hash","duration_seconds":2,"sample_rate":8000,"channels":1,"original_token":"original","playback_token":"original","peaks":[],"anchors":[]}),))
    store = SQLiteProjectStore(path)
    assert store.active_project_id() == config.id
    old = store.for_project(config.id)
    assert old.config == config
    assert old.get_version(doc.id).document == doc
    assert old.get_artifact("original").data == b"source bytes"
    assert old.get_reference("reference").id == "reference"
    other = store.create_project("New piece")
    assert store.list_versions() == []
    with pytest.raises(VersionNotFound):
        store.get_version(doc.id)
    with pytest.raises(ArtifactNotFound):
        store.get_artifact("original")
    assert old.get_version(doc.id).document == doc
    store.close()
    reopened = SQLiteProjectStore(path)
    assert reopened.active_project_id() == other.id
    assert len(reopened.list_projects()) == 2
    assert reopened.for_project(config.id).get_artifact("original").data == b"source bytes"
    reopened.close()
