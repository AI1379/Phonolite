"""FastAPI music lab: actual notes, regional analysis, audio and explicit choice."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
import wave

from fastapi.testclient import TestClient

from workbench_server.memory import get_memory_store


def test_note_pages_and_track_only_analysis(client: TestClient, imported_main: str) -> None:
    url = f"/api/score/{imported_main}"
    first = client.get(url, params={"limit": 2}).json()["result"]
    assert len(first["notes"]) == 2
    assert first["next_offset"] == 2
    second = client.get(url, params={"offset": 2, "limit": 2}).json()["result"]
    assert {n["id"] for n in first["notes"]}.isdisjoint(n["id"] for n in second["notes"])
    findings = client.get(url + "/inspect", params={"track_ids": "track-1"}).json()["result"]["findings"]
    assert findings
    assert all(f["location"]["track_ids"] == ["track-1"] for f in findings)
    assert client.get(url, params={"track_ids": "missing"}).status_code == 422


def test_music_experiment_produces_two_actual_wavs_without_accepting(client: TestClient, imported_main: str) -> None:
    url = f"/api/score/{imported_main}"
    notes = client.get(url).json()["result"]["notes"]
    selected = notes[0]
    response = client.post("/api/score/transform", json={
        "source_version_id": imported_main,
        "region": {"start_beat": 0, "end_beat": 16},
        "operation": "shift_note_onset",
        "parameters": {"note_id": selected["id"], "shift_beats": 0.5},
    })
    assert response.status_code == 200, response.text
    candidate = response.json()["result"]["version"]["version_id"]
    assert client.get("/api/project").json()["result"]["active_version"] == imported_main
    artifacts: list[bytes] = []
    for version in (imported_main, candidate):
        rendered = client.post(f"/api/score/{version}/render", params={"backend": "preview"})
        assert rendered.status_code == 200, rendered.text
        result = rendered.json()["result"]
        download = client.get(f"/api/artifact/{result['artifact_token']}")
        assert download.headers["content-type"] == "audio/wav"
        with wave.open(BytesIO(download.content)) as wav:
            assert wav.getnframes() > 1000
        artifacts.append(download.content)
    assert artifacts[0] != artifacts[1]
    compared = client.post("/api/score/compare", json={"before_version_id": imported_main, "after_version_id": candidate}).json()["result"]
    assert len(compared["modified"]) == 1
    chosen = client.post("/api/project/choose", json={"chosen_version_id": candidate, "reason": "The later attack leaves more space"})
    assert chosen.status_code == 200


def test_second_import_keeps_project_and_memory_active_version_consistent(
    client: TestClient, make_piano_b64: Callable[..., str],
) -> None:
    first = client.post("/api/score/import", json={"midi_b64": make_piano_b64(bars=2)}).json()["result"]["version"]["version_id"]
    client.post("/api/score/import", json={"midi_b64": make_piano_b64(bars=4)})
    status = client.get("/api/project").json()["result"]
    entry = next(item for item in get_memory_store().list_project_state(status["project"]["id"]) if item.key == "active_version")
    assert first == status["active_version"] == entry.value


def test_audio_supports_byte_ranges_for_browser_seeking(client: TestClient, imported_main: str) -> None:
    result = client.post(f"/api/score/{imported_main}/render", params={"backend": "preview"}).json()["result"]
    url = f"/api/artifact/{result['artifact_token']}"
    full = client.get(url)
    part = client.get(url, headers={"Range": "bytes=44-127"})
    assert part.status_code == 206
    assert part.content == full.content[44:128]
    assert part.headers["content-range"] == f"bytes 44-127/{len(full.content)}"
    suffix = client.get(url, headers={"Range": "bytes=-32"})
    assert suffix.content == full.content[-32:]
    assert client.get(url, headers={"Range": "bytes=999999999-"}).status_code == 416


def test_malformed_midi_and_query_return_error_envelopes(client: TestClient, imported_main: str) -> None:
    import base64
    response = client.post("/api/score/import", json={"midi_b64": base64.b64encode(b"not midi").decode()})
    assert response.status_code == 422
    assert response.json()["ok"] is False
    response = client.get(f"/api/score/{imported_main}", params={"limit": 0})
    assert response.status_code == 422
    assert response.json()["ok"] is False
