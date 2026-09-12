"""Audio-to-draft workflow and recovery using a newly opened SQLite connection."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
import wave
import sqlite3

import numpy as np
import pytest
from fastapi.testclient import TestClient

from workbench_server.store import configure_project_store, get_store


def _audio_bytes() -> bytes:
    stream = BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        samples = (np.sin(2 * np.pi * 440 * np.arange(4 * 8000) / 8000) * 10000).astype("<i2")
        wav.writeframes(samples.tobytes())
    return stream.getvalue()


def test_reference_draft_corrections_and_assets_survive_reopen(client: TestClient) -> None:
    raw = _audio_bytes()
    imported = client.post("/api/references/import", json={"filename": "原曲.wav", "audio_b64": base64.b64encode(raw).decode()})
    assert imported.status_code == 200, imported.text
    reference = imported.json()["result"]["reference"]
    assert reference["anchors"] == []
    assert len(reference["peaks"]) == 1600
    assert client.get("/api/artifact/" + reference["original_token"]).content == raw
    duplicate = client.post("/api/references/import", json={"filename": "same.wav", "audio_b64": base64.b64encode(raw).decode()})
    assert duplicate.json()["result"]["reference"]["id"] == reference["id"]
    anchors = [{"seconds": 1, "beat": 0}, {"seconds": 3, "beat": 4}]
    saved = client.put(f"/api/references/{reference['id']}/alignment", json={"anchors": anchors})
    assert saved.status_code == 200, saved.text
    draft = client.post("/api/score/draft", json={"title": "扒谱", "reference_id": reference["id"]}).json()["result"]["version"]
    assert draft["duration_beats"] == 4
    added = client.post("/api/score/edit", json={"source_version_id": draft["version_id"], "action": "add", "note": {
        "pitch": 60, "onset_beats": 1, "duration_beats": 1, "role": "melody", "transcription_status": "uncertain"
    }})
    assert added.status_code == 200, added.text
    add_id = added.json()["result"]["version"]["version_id"]
    note = client.get(f"/api/score/{add_id}").json()["result"]["notes"][0]
    corrected = client.post("/api/score/edit", json={"source_version_id": add_id, "action": "update", "note_id": note["id"], "note": {
        "pitch": 62, "onset_beats": 1, "duration_beats": 0.5, "role": "melody", "transcription_status": "confirmed"
    }})
    assert corrected.status_code == 200, corrected.text
    corrected_id = corrected.json()["result"]["version"]["version_id"]
    render = client.post(f"/api/score/{corrected_id}/render", params={"backend": "preview"}).json()["result"]
    before = client.get("/api/project").json()["result"]
    assert before["active_version"] == draft["version_id"]
    assert before["working_version"] == corrected_id
    configure_project_store(get_store().path)
    after = client.get("/api/project").json()["result"]
    assert after == before
    restored = client.get(f"/api/score/{corrected_id}").json()["result"]["notes"][0]
    assert restored["id"] == note["id"]
    assert restored["pitch"] == 62
    assert restored["transcription_status"] == "confirmed"
    assert restored["reference_evidence"]["start_seconds"] == 1.5
    assert client.get(f"/api/score/{add_id}").json()["result"]["notes"][0]["pitch"] == 60
    assert client.get("/api/artifact/" + reference["original_token"]).content == raw
    assert client.get("/api/references").json()["result"]["references"][0]["anchors"] == anchors
    audio = client.get("/api/artifact/" + render["artifact_token"])
    assert audio.content[:4] == b"RIFF"
    assert client.get("/api/artifact/" + reference["playback_token"], headers={"Range": "bytes=0-43"}).status_code == 206


def test_bad_alignment_and_edit_do_not_commit_partial_state(client: TestClient) -> None:
    reference = client.post("/api/references/import", json={"filename": "audio.wav", "audio_b64": base64.b64encode(_audio_bytes()).decode()}).json()["result"]["reference"]
    bad = client.put(f"/api/references/{reference['id']}/alignment", json={"anchors": [{"seconds": 0, "beat": 0}, {"seconds": 5, "beat": 8}]})
    assert bad.status_code == 422
    assert client.get("/api/references").json()["result"]["references"][0]["anchors"] == []
    assert client.post("/api/score/draft", json={"reference_id": reference["id"]}).status_code == 422
    draft = client.post("/api/score/draft", json={}).json()["result"]["version"]
    before = client.get("/api/project").json()["result"]
    assert client.post("/api/score/edit", json={"source_version_id": draft["version_id"], "action": "add", "note": {"pitch": 60, "onset_beats": 0, "duration_beats": -1}}).status_code == 422
    assert client.get("/api/project").json()["result"] == before


def test_bad_audio_leaves_no_reference_records(client: TestClient) -> None:
    response = client.post("/api/references/import", json={"filename": "bad.mp3", "audio_b64": base64.b64encode(b"invalid").decode()})
    assert response.status_code == 422
    assert client.get("/api/references").json()["result"]["references"] == []


def test_full_score_storage_returns_isolated_objects(tmp_path: Path) -> None:
    from music_core.edit import NoteValues, create_draft, edit_note
    from workbench_server.persistence import SQLiteProjectStore
    store = SQLiteProjectStore(tmp_path / "native.db")
    doc = edit_note(create_draft(title="test"), action="add", values=NoteValues(60, 0, 1))
    store.add_version(doc, parent_id=None, branch="draft", origin="draft", description="test")
    doc.notes[0].pitch = 99
    assert store.get_version(doc.id).document.notes[0].pitch == 60
    with pytest.raises(sqlite3.IntegrityError):
        store.add_version(doc, parent_id=None, branch="draft", origin="draft", description="duplicate ID")
    assert store.get_version(doc.id).document.notes[0].pitch == 60
    store.close()


@pytest.mark.parametrize("format_name", ["WAV", "FLAC", "OGG", "MP3"])
def test_supported_reference_formats_decode_to_playable_wav(format_name: str) -> None:
    import soundfile as sf
    from workbench_server.assets import prepare_audio
    stream = BytesIO()
    samples = np.sin(2 * np.pi * 440 * np.arange(22050) / 44100).reshape(-1, 1) * 0.2
    sf.write(stream, samples, 44100, format=format_name)
    data = stream.getvalue()
    result = prepare_audio(data, "reference." + format_name.lower())
    assert result.original == data
    assert 0.4 <= result.duration_seconds <= 0.7
    assert result.playback is not None
    assert result.playback[:4] == b"RIFF"
    assert len(result.peaks) == 1600
