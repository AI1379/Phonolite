"""Tests for channel planning, retrieval policy, and quotas."""

from __future__ import annotations

from memory_core import ClaimType, RecallPlanner, SQLiteMemoryStore, recall


def test_planner_separates_channels_and_hides_raw_history_by_default() -> None:
    plan = RecallPlanner().plan(project_id="p1", subject_id="user")

    assert plan.channels == (
        "user_preferences",
        "active_project",
        "recent_project_episodes",
        "learning_state",
    )
    assert plan.need_raw_history is False
    assert "raw_history" not in plan.channels


def test_recall_uses_confirmed_preferences_and_channel_limits() -> None:
    store = SQLiteMemoryStore()
    confirmed = store.propose_claim(
        actor_id="user",
        project_id="p1",
        subject_type="person",
        subject_id="user",
        predicate="prefers_sparse_bass",
        value={"description": "leave room before resolution"},
        claim_type=ClaimType.PREFERENCE,
    )
    store.confirm_claim(confirmed.id, actor_id="user")
    store.propose_claim(
        actor_id="user",
        project_id="p1",
        subject_type="person",
        subject_id="user",
        predicate="prefers_dense_bass",
        value={"description": "one local choice only"},
        claim_type=ClaimType.PREFERENCE,
    )
    for index in range(3):
        store.record_episode(
            actor_id="person:user",
            project_id="p1",
            summary=f"Episode {index}",
        )

    plan = RecallPlanner().plan(
        project_id="p1", subject_id="user", per_channel_limit=1
    )
    view = recall(store, plan, query="sparse")

    preferences = [item for item in view.items if item.channel == "user_preferences"]
    episodes = [item for item in view.items if item.channel == "recent_project_episodes"]
    assert [item.id for item in preferences] == [confirmed.id]
    assert len(episodes) == 1
    assert all(item.kind != "raw_event" for item in view.items)
    store.close()


def test_raw_history_requires_explicit_plan_flag() -> None:
    store = SQLiteMemoryStore()
    event = store.record_episode(
        actor_id="user", project_id="p1", summary="Private working note"
    )
    plan = RecallPlanner().plan(
        project_id="p1", subject_id="user", need_raw_history=True
    )

    view = recall(store, plan)

    assert any(item.id == event.id and item.kind == "raw_event" for item in view.items)
    store.close()
