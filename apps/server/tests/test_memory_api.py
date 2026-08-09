"""Domain API tests for MVP-2 memory and learning tools."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_record_episode_and_query_observation(client: TestClient) -> None:
    recorded = client.post(
        "/api/memory/episodes",
        json={
            "project_id": "lake-tower",
            "summary": "Compared delayed and immediate bass resolution",
            "details": {"bars": [1, 8]},
        },
    )
    assert recorded.status_code == 200
    result = recorded.json()["result"]
    assert result["event"]["event_type"] == "episode.recorded"
    assert result["observation"]["source_event_id"] == result["event"]["id"]

    queried = client.post(
        "/api/memory/query",
        json={"project_id": "lake-tower", "subject_id": "user"},
    )
    assert queried.status_code == 200
    recall = queried.json()["result"]
    assert "raw_history" not in recall["plan"]["channels"]
    assert any(
        item["kind"] == "observation"
        and "delayed and immediate" in item["summary"]
        for item in recall["items"]
    )


def test_claim_requires_explicit_confirmation(client: TestClient) -> None:
    proposed = client.post(
        "/api/memory/claims",
        json={
            "project_id": "lake-tower",
            "subject_type": "person",
            "subject_id": "user",
            "predicate": "prefers_delayed_resolution",
            "value": {"reason": "clearer direction"},
            "claim_type": "preference",
            "confidence": 0.6,
        },
    )
    assert proposed.status_code == 200
    claim_id = proposed.json()["result"]["claim"]["id"]
    assert proposed.json()["result"]["state"]["status"] == "proposed"

    before = client.post(
        "/api/memory/query",
        json={"project_id": "lake-tower", "subject_id": "user"},
    ).json()
    assert all(item["id"] != claim_id for item in before["result"]["items"])

    confirmed = client.post(
        f"/api/memory/claims/{claim_id}/confirm", json={"actor_id": "person:user"}
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["result"]["state"]["status"] == "confirmed"

    after = client.post(
        "/api/memory/query",
        json={"project_id": "lake-tower", "subject_id": "user"},
    ).json()
    assert any(item["id"] == claim_id for item in after["result"]["items"])


def test_unknown_claim_confirmation_returns_envelope_404(client: TestClient) -> None:
    response = client.post(
        "/api/memory/claims/missing/confirm", json={"actor_id": "person:user"}
    )
    assert response.status_code == 404
    assert response.json()["ok"] is False


def test_learning_outcome_updates_structured_state(client: TestClient) -> None:
    response = client.post(
        "/api/learning/outcomes",
        json={
            "project_id": "lake-tower",
            "focus": "delayed-resolution",
            "status": "understood",
            "mastery": 0.75,
            "evidence": "Explained why the second variant has more direction",
        },
    )
    assert response.status_code == 200
    state = response.json()["result"]["learning_state"]
    assert state["focus"] == "delayed-resolution"
    assert state["mastery"] == 0.75
    assert state["evidence_count"] == 1


def test_choose_projects_decision_preference_and_learning(
    client: TestClient, imported_main: str
) -> None:
    chosen = client.post(
        "/api/project/choose",
        json={
            "chosen_version_id": imported_main,
            "experiment_id": "exp-017",
            "reason": "The delayed arrival creates direction",
            "learning_focus": "delayed-resolution",
            "tags": ["bass"],
        },
    )
    assert chosen.status_code == 200
    projection = chosen.json()["result"]["memory_projection"]
    assert projection["decision_claim_id"]
    assert projection["preference_claim_id"]

    project_id = chosen.json()["result"]["project"]["id"]
    state = client.get(f"/api/memory/project/{project_id}")
    assert state.status_code == 200
    state_by_key = {
        item["key"]: item["value"] for item in state.json()["result"]["project_state"]
    }
    assert state_by_key["active_version"] == imported_main
    counts = state.json()["result"]["projection_counts"]
    assert counts["learning_state"] == 1
    assert counts["claims"] == 2
