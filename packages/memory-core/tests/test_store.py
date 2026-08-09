"""Tests for the immutable ledger and typed memory projections."""

from __future__ import annotations

from pathlib import Path

import pytest

from memory_core import (
    ClaimStatus,
    ClaimType,
    ExperimentOutcome,
    SQLiteMemoryStore,
    Sensitivity,
)


def test_events_are_immutable_and_persist(tmp_path: Path) -> None:
    database = tmp_path / "project.db"
    store = SQLiteMemoryStore(database)
    event = store.record_episode(
        actor_id="person:user",
        project_id="lake-tower",
        summary="Compared two bass-resolution variants",
    )

    with pytest.raises(ValueError, match="already exists"):
        store.record_event(
            event_type=event.event_type,
            actor_id=event.actor_id,
            project_id=event.project_id,
            payload=event.payload,
            event_id=event.id,
        )
    store.close()

    reopened = SQLiteMemoryStore(database)
    assert reopened.get_event(event.id) == event
    assert reopened.list_observations(project_id="lake-tower")[0].source_event_id == event.id
    reopened.close()


def test_claim_lifecycle_and_fail_closed_policy() -> None:
    store = SQLiteMemoryStore()
    claim = store.propose_claim(
        actor_id="person:user",
        project_id="lake-tower",
        subject_type="person",
        subject_id="user",
        predicate="prefers_delayed_resolution",
        value={"strength": "tentative"},
        claim_type=ClaimType.PREFERENCE,
        confidence=0.6,
        sensitivity="unrecognised-label",
        visibility="public",
    )

    _, proposed, policy = store.get_claim(claim.id)
    assert proposed.status is ClaimStatus.PROPOSED
    assert policy.sensitivity is Sensitivity.QUARANTINE
    assert policy.visibility == "private"

    confirmed = store.confirm_claim(claim.id, actor_id="person:user")
    assert confirmed.status is ClaimStatus.CONFIRMED
    assert confirmed.confidence == 1.0
    assert confirmed.last_confirmed_at is not None

    with pytest.raises(ValueError):
        ClaimType("invented-by-model")
    store.close()


def test_learning_outcome_updates_explicit_state() -> None:
    store = SQLiteMemoryStore()
    first = store.record_learning_outcome(
        actor_id="person:user",
        subject_id="user",
        project_id="lake-tower",
        focus="delayed-resolution",
        status="practicing",
        mastery=0.35,
        evidence="Could identify the delayed bass arrival",
    )
    second = store.record_learning_outcome(
        actor_id="person:user",
        subject_id="user",
        project_id="lake-tower",
        focus="delayed-resolution",
        status="understood",
        mastery=0.7,
        evidence="Explained the A/B difference without prompting",
    )

    assert first.evidence_count == 1
    assert second.status == "understood"
    assert second.mastery == 0.7
    assert second.evidence_count == 2
    store.close()


def test_experiment_outcome_has_multiple_safe_projections() -> None:
    store = SQLiteMemoryStore()
    projection = store.record_experiment_outcome(
        ExperimentOutcome(
            project_id="lake-tower",
            subject_id="user",
            experiment_id="exp-017",
            chosen_version_id="v013",
            reason="The delayed bass creates direction without adding density",
            learning_focus="delayed-resolution",
            tags=("bass", "delayed-resolution"),
        )
    )

    observation = store.get_observation(projection.observation_id)
    assert observation.context == "experiment:exp-017"
    _, decision_state, _ = store.get_claim(projection.decision_claim_id)
    assert decision_state.status is ClaimStatus.CONFIRMED
    assert projection.preference_claim_id is not None
    _, preference_state, _ = store.get_claim(projection.preference_claim_id)
    assert preference_state.status is ClaimStatus.PROPOSED
    assert {item.key: item.value for item in store.list_project_state("lake-tower")}[
        "active_version"
    ] == "v013"
    learning = store.get_learning_state(
        "user", "delayed-resolution", project_id="lake-tower"
    )
    assert learning.status == "practicing"
    store.close()


def test_confidence_range_is_validated() -> None:
    store = SQLiteMemoryStore()
    with pytest.raises(ValueError, match="between"):
        store.record_observation(
            actor_id="agent",
            project_id=None,
            subject="person:user",
            event="Impossible confidence",
            context=None,
            confidence=1.1,
        )
    store.close()
