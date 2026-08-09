"""End-to-end test for the recommended first vertical slice (design doc 19).

Covers the whole chain in one shot::

    MIDI Import -> Score IR -> Project Goal -> Inspect
    -> Delayed Resolution Transform -> Semantic Diff -> Render
    -> A/B Selection -> Project Decision (+ learning reason)

The learning event is captured as the decision's reason/tags here; the
structured learning state arrives in MVP-2. Rendering uses the always-on
MIDI fallback so the slice runs in any environment without a synth.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient


def test_first_vertical_slice(
    client: TestClient, make_piano_b64: Callable[..., str]
) -> None:
    # MIDI Import -> Score IR
    imported = client.post(
        "/api/score/import",
        json={
            "midi_b64": make_piano_b64(bars=8),
            "project_id": "lake-tower",
            "title": "Lake Tower",
        },
    ).json()
    main_id = imported["result"]["version"]["version_id"]
    assert imported["result"]["version"]["note_count"] == 24  # 8 bars * 3

    # Project Goal
    goal = client.patch(
        "/api/project/goal",
        json={"description": "destabilise without breaking", "bars": [1, 8]},
    ).json()
    assert goal["result"]["project"]["current_goal"]["region"]["bars"] == [1, 8]

    # Inspect -> the analyses flag a static / repetitive feeling
    inspected = client.get(f"/api/score/{main_id}/inspect").json()["result"]
    interpretations = " ".join(
        f["interpretation"] for f in inspected["findings"]
    ).lower()
    assert "static" in interpretations or "repetition" in interpretations

    # Delayed Resolution Transform -> candidate variant
    transform = client.post(
        "/api/score/transform",
        json={
            "source_version_id": main_id,
            "region": {"start_beat": 0.0, "end_beat": 32.0},
            "operation": "delay_bass_resolution",
            "parameters": {"delay_beats": 1.0},
        },
    ).json()
    variant_id = transform["result"]["version"]["version_id"]
    assert len(transform["result"]["changed_event_ids"]) == 8  # one bass per bar

    # Semantic Diff -> only the bass moved (ids preserved)
    diff_result = client.post(
        "/api/score/compare",
        json={"before_version_id": main_id, "after_version_id": variant_id},
    ).json()["result"]
    assert diff_result["is_empty"] is False
    moved = [c for c in diff_result["modified"] if c["kind"] == "moved"]
    assert len(moved) == 8
    assert diff_result["added"] == []
    assert diff_result["removed"] == []

    # Render -> downloadable artifact
    render = client.post(
        f"/api/score/{variant_id}/render", params={"backend": "midi"}
    ).json()["result"]
    download = client.get(f"/api/artifact/{render['artifact_token']}")
    assert download.status_code == 200
    assert download.content[:4] == b"MThd"

    # A/B Selection + Project Decision, with a learning-flavoured reason
    chosen = client.post(
        "/api/project/choose",
        json={
            "chosen_version_id": variant_id,
            "reason": "delaying the bass keeps each bar from resolving too early",
            "tags": ["bass", "timing", "motif_development"],
        },
    ).json()["result"]
    assert chosen["decision"]["chosen_version_id"] == variant_id

    # Project state now reflects the decision and the version tree.
    status = client.get("/api/project").json()["result"]
    assert status["active_version"] == variant_id
    decisions = status["project"]["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["chosen_version_id"] == variant_id
    assert "motif_development" in decisions[0]["tags"]
    assert len(status["versions"]) == 2  # main + variant
