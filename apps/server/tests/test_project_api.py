"""Domain API tests for the project tools (design doc section 8.1)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_default_project_status(client: TestClient) -> None:
    resp = client.get("/api/project")
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["active_version"] is None
    assert result["versions"] == []
    assert result["project"]["title"]  # a default title exists
    assert result["project"]["id"].startswith("project-")


def test_update_goal_with_bars(client: TestClient) -> None:
    resp = client.patch(
        "/api/project/goal",
        json={"description": "destabilise bars 1-8", "bars": [1, 8]},
    )
    assert resp.status_code == 200
    goal = resp.json()["result"]["project"]["current_goal"]
    assert goal["description"] == "destabilise bars 1-8"
    assert goal["region"]["bars"] == [1, 8]


def test_update_goal_without_region(client: TestClient) -> None:
    resp = client.patch(
        "/api/project/goal",
        json={"description": "broad exploration, no fixed region"},
    )
    assert resp.status_code == 200
    project = resp.json()["result"]["project"]
    assert project["current_goal"]["description"] == "broad exploration, no fixed region"
    assert "region" not in project["current_goal"]


def test_record_decision_appends_to_audit_log(client: TestClient, imported_main: str) -> None:
    resp = client.post(
        "/api/project/decision",
        json={
            "summary": "pick the late-bass variant",
            "chosen_version_id": imported_main,
            "reason": "tension is kept longer",
            "tags": ["bass", "timing"],
        },
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    decision = result["decision"]
    assert decision["summary"] == "pick the late-bass variant"
    assert decision["chosen_version_id"] == imported_main
    assert decision["reason"] == "tension is kept longer"
    assert decision["tags"] == ["bass", "timing"]
    assert decision["id"].startswith("decision_")
    assert decision["at"]  # ISO timestamp present
    # Persisted into the project config's decisions list.
    assert result["project"]["decisions"][0]["id"] == decision["id"]


def test_accept_unknown_variant_404(client: TestClient) -> None:
    resp = client.post("/api/project/accept", json={"version_id": "nope"})
    assert resp.status_code == 404


def test_accept_variant_sets_active(
    imported_main: str, client: TestClient
) -> None:
    resp = client.post("/api/project/accept", json={"version_id": imported_main})
    assert resp.status_code == 200
    assert resp.json()["result"]["active_version"] == imported_main


def test_choose_records_decision_and_accepts_variant(
    imported_main: str, client: TestClient
) -> None:
    # Make a variant via transform, then choose it (A/B selection step).
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
        "/api/project/choose",
        json={
            "chosen_version_id": variant_id,
            "reason": "the delayed bass keeps tension",
            "tags": ["bass", "timing"],
        },
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["decision"]["chosen_version_id"] == variant_id
    assert result["decision"]["reason"] == "the delayed bass keeps tension"
    assert result["active_version"] if "active_version" in result else True

    # The variant is now the active version and a decision was recorded.
    status = client.get("/api/project").json()["result"]
    assert status["active_version"] == variant_id
    decisions = status["project"]["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["chosen_version_id"] == variant_id


def test_choose_unknown_variant_404(client: TestClient) -> None:
    resp = client.post("/api/project/choose", json={"chosen_version_id": "nope"})
    assert resp.status_code == 404
