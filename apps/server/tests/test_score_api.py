"""Domain API tests for the score tools (design doc section 8.2)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient


def test_import_returns_version_summary_and_sets_active(
    client: TestClient, make_piano_b64: Callable[..., str]
) -> None:
    resp = client.post(
        "/api/score/import",
        json={
            "midi_b64": make_piano_b64(bars=4),
            "project_id": "p1",
            "title": "Lake Tower",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["provenance"]["tool"] == "import_score"
    assert body["warnings"] == []

    version = body["result"]["version"]
    assert version["origin"] == "import"
    assert version["branch"] == "main"
    assert version["note_count"] == 12  # 4 bars * 3 notes
    # MIDI round-trip renumbers tracks positionally (track-0, track-1, ...).
    assert version["track_ids"] == ["track-0", "track-1"]
    assert version["meters"] == [{"beat": 0.0, "numerator": 4, "denominator": 4}]

    # First import is promoted to the active version explicitly.
    status = client.get("/api/project").json()["result"]
    assert status["active_version"] == version["version_id"]
    assert len(status["versions"]) == 1
    assert status["project"]["title"] == "Lake Tower"


def test_inspect_returns_locatable_findings(
    imported_main: str, client: TestClient
) -> None:
    resp = client.get(f"/api/score/{imported_main}/inspect")
    assert resp.status_code == 200, resp.text
    body = resp.json()["result"]
    assert body["version_id"] == imported_main
    findings = body["findings"]
    # register (>=1) + density (1) + bass (1).
    assert len(findings) >= 3
    # Every finding is locatable and hedged (design red lines).
    for finding in findings:
        assert "location" in finding
        assert "confidence" in finding
        assert isinstance(finding["evidence"], list)


def test_inspect_with_region_query(
    imported_main: str, client: TestClient
) -> None:
    resp = client.get(
        f"/api/score/{imported_main}/inspect",
        params={"start_beat": 0.0, "end_beat": 4.0},
    )
    assert resp.status_code == 200
    brief = resp.json()["result"]["region"]
    assert brief["scope"] == "region"
    assert brief["start_beat"] == 0.0
    assert brief["end_beat"] == 4.0


def test_inspect_region_requires_both_bounds(
    imported_main: str, client: TestClient
) -> None:
    resp = client.get(
        f"/api/score/{imported_main}/inspect", params={"start_beat": 0.0}
    )
    assert resp.status_code == 422
    assert resp.json()["ok"] is False


def test_inspect_unknown_version_404(client: TestClient) -> None:
    resp = client.get("/api/score/nope/inspect")
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert "version not found" in body["result"]["error"]


def test_transform_creates_new_version_on_branch(
    imported_main: str, client: TestClient
) -> None:
    resp = client.post(
        "/api/score/transform",
        json={
            "source_version_id": imported_main,
            "region": {"start_beat": 0.0, "end_beat": 16.0},
            "operation": "delay_bass_resolution",
            "parameters": {"delay_beats": 1.0},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provenance"]["tool"] == "apply_transformation"
    result = body["result"]

    new_id = result["version"]["version_id"]
    assert new_id != imported_main
    assert result["version"]["parent_version"] == imported_main
    assert result["operation"] == "delay_bass_resolution"
    assert result["branch"] == "exp/delayed-bass"
    # Four bass notes (one per bar) were shifted.
    assert len(result["changed_event_ids"]) == 4
    assert result["validation"]["ok"] is True

    versions = client.get("/api/project").json()["result"]["versions"]
    assert any(v["version_id"] == new_id for v in versions)


def test_transform_then_compare_shows_bass_moved(
    imported_main: str, client: TestClient
) -> None:
    transform = client.post(
        "/api/score/transform",
        json={
            "source_version_id": imported_main,
            "region": {"start_beat": 0.0, "end_beat": 16.0},
            "operation": "delay_bass_resolution",
            "parameters": {"delay_beats": 1.0},
        },
    ).json()
    variant_id = transform["result"]["version"]["version_id"]

    resp = client.post(
        "/api/score/compare",
        json={"before_version_id": imported_main, "after_version_id": variant_id},
    )
    assert resp.status_code == 200
    diff_result = resp.json()["result"]
    assert diff_result["is_empty"] is False
    # IDs are preserved, so everything shows up as modifications (no add/remove).
    assert diff_result["added"] == []
    assert diff_result["removed"] == []
    moved = [c for c in diff_result["modified"] if c["kind"] == "moved"]
    assert len(moved) == 4
    assert all("onset_beats" in c["field_changes"] for c in moved)
    # unchanged count covers the 8 non-bass notes
    assert diff_result["unchanged_count"] == 8


def test_compare_identical_versions_is_empty(
    imported_main: str, client: TestClient
) -> None:
    resp = client.post(
        "/api/score/compare",
        json={"before_version_id": imported_main, "after_version_id": imported_main},
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["is_empty"] is True


def test_render_midi_backend_produces_downloadable_artifact(
    imported_main: str, client: TestClient
) -> None:
    resp = client.post(f"/api/score/{imported_main}/render", params={"backend": "midi"})
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["backend"] == "midi-file"
    token = result["artifact_token"]
    assert result["size_bytes"] > 0

    download = client.get(f"/api/artifact/{token}")
    assert download.status_code == 200
    assert download.headers["content-type"] == "audio/midi"
    assert download.content[:4] == b"MThd"  # SMF magic


def test_export_produces_midi_artifact(
    imported_main: str, client: TestClient
) -> None:
    resp = client.post(f"/api/score/{imported_main}/export")
    assert resp.status_code == 200
    result = resp.json()["result"]
    token = result["artifact_token"]
    assert result["filename"].endswith(".mid")

    download = client.get(f"/api/artifact/{token}")
    assert download.status_code == 200
    assert download.content[:4] == b"MThd"


def test_transform_unknown_version_404(client: TestClient) -> None:
    resp = client.post(
        "/api/score/transform",
        json={
            "source_version_id": "nope",
            "region": {"start_beat": 0.0, "end_beat": 4.0},
            "operation": "delay_bass_resolution",
            "parameters": {"delay_beats": 1.0},
        },
    )
    assert resp.status_code == 404


def test_transform_unknown_operation_422(
    imported_main: str, client: TestClient
) -> None:
    resp = client.post(
        "/api/score/transform",
        json={
            "source_version_id": imported_main,
            "region": {"start_beat": 0.0, "end_beat": 4.0},
            "operation": "bogus",
            "parameters": {},
        },
    )
    assert resp.status_code == 422


def test_transform_invalid_factor_422(
    imported_main: str, client: TestClient
) -> None:
    resp = client.post(
        "/api/score/transform",
        json={
            "source_version_id": imported_main,
            "region": {"start_beat": 0.0, "end_beat": 4.0},
            "operation": "rhythmic_scaling",
            "parameters": {"factor": 0.0},
        },
    )
    assert resp.status_code == 422


def test_rhythmic_scaling_transform(
    imported_main: str, client: TestClient
) -> None:
    resp = client.post(
        "/api/score/transform",
        json={
            "source_version_id": imported_main,
            "region": {"start_beat": 0.0, "end_beat": 16.0},
            "operation": "rhythmic_scaling",
            "parameters": {"factor": 2.0},
            "output_branch": "exp/augmentation",
        },
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["operation"] == "rhythmic_scaling"
    assert result["branch"] == "exp/augmentation"
    assert len(result["changed_event_ids"]) == 12


def test_invalid_base64_422(client: TestClient) -> None:
    resp = client.post("/api/score/import", json={"midi_b64": "not base64!!!"})
    assert resp.status_code == 422


def test_compare_unknown_version_404(
    imported_main: str, client: TestClient
) -> None:
    resp = client.post(
        "/api/score/compare",
        json={"before_version_id": imported_main, "after_version_id": "nope"},
    )
    assert resp.status_code == 404
