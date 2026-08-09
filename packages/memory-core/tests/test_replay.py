"""Replay benchmark: projections must be reproducible from raw events."""

from __future__ import annotations

from memory_core import ClaimType, ExperimentOutcome, SQLiteMemoryStore


def test_replay_rebuilds_identical_projection_state() -> None:
    store = SQLiteMemoryStore()
    claim = store.propose_claim(
        actor_id="user",
        project_id="p1",
        subject_type="person",
        subject_id="user",
        predicate="prefers_clear_resolution",
        value={"degree": "tentative"},
        claim_type=ClaimType.PREFERENCE,
        confidence=0.65,
    )
    store.confirm_claim(claim.id, actor_id="user")
    outcome = store.record_experiment_outcome(
        ExperimentOutcome(
            project_id="p1",
            subject_id="user",
            experiment_id="exp-1",
            chosen_version_id="v2",
            reason="The arrival is easier to hear",
            learning_focus="harmonic-rhythm",
        )
    )
    store.record_learning_outcome(
        actor_id="user",
        subject_id="user",
        project_id="p1",
        focus="harmonic-rhythm",
        status="understood",
        mastery=0.8,
        evidence="Explained the resolution point",
    )
    before_counts = store.projection_counts()
    before_claim = store.get_claim(claim.id)
    before_decision = store.get_claim(outcome.decision_claim_id)
    before_project = store.list_project_state("p1")
    before_learning = store.list_learning_state(subject_id="user", project_id="p1")

    store.replay()

    assert store.projection_counts() == before_counts
    assert store.get_claim(claim.id) == before_claim
    assert store.get_claim(outcome.decision_claim_id) == before_decision
    assert store.list_project_state("p1") == before_project
    assert store.list_learning_state(subject_id="user", project_id="p1") == before_learning
    store.close()
