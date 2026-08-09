"""Channel-aware recall planning and retrieval."""

from __future__ import annotations

from memory_core.models import (
    ClaimStatus,
    ClaimType,
    JsonObject,
    MemoryClaim,
    MemoryPolicy,
    RecallItem,
    RecallPlan,
    RecallView,
    Sensitivity,
)
from memory_core.store import SQLiteMemoryStore


class RecallPlanner:
    """Build an explicit multi-channel plan before touching stored memory."""

    def plan(
        self,
        *,
        project_id: str | None,
        subject_id: str | None,
        need_raw_history: bool = False,
        time_horizon: str = "long",
        per_channel_limit: int = 5,
    ) -> RecallPlan:
        if per_channel_limit < 1:
            raise ValueError("per_channel_limit must be positive")
        channels: list[str] = []
        entities: list[str] = []
        if subject_id is not None:
            channels.append("user_preferences")
            entities.append(f"person:{subject_id}")
        if project_id is not None:
            channels.extend(("active_project", "recent_project_episodes"))
            entities.append(f"project:{project_id}")
        if subject_id is not None:
            channels.append("learning_state")
        if need_raw_history:
            channels.append("raw_history")
        return RecallPlan(
            channels=tuple(channels),
            entities=tuple(entities),
            time_horizon=time_horizon,
            need_raw_history=need_raw_history,
            channel_limits={channel: per_channel_limit for channel in channels},
        )


def recall(
    store: SQLiteMemoryStore,
    plan: RecallPlan,
    *,
    query: str = "",
) -> RecallView:
    """Retrieve each channel independently, then combine and rank its results."""
    project_id = _entity_id(plan.entities, "project")
    subject_id = _entity_id(plan.entities, "person")
    gathered: list[RecallItem] = []
    for channel in plan.channels:
        limit = plan.channel_limits.get(channel, 5)
        candidates: list[RecallItem]
        if channel == "user_preferences" and subject_id is not None:
            candidates = _preference_items(store, subject_id, project_id)
        elif channel == "active_project" and project_id is not None:
            candidates = _project_items(store, project_id)
        elif channel == "recent_project_episodes" and project_id is not None:
            candidates = [
                RecallItem(
                    channel=channel,
                    kind="observation",
                    id=item.id,
                    summary=item.event,
                    confidence=item.confidence,
                    occurred_at=item.observed_at,
                    data={
                        "subject": item.subject,
                        "context": item.context,
                        "source_event_id": item.source_event_id,
                    },
                )
                for item in store.list_observations(project_id=project_id)
            ]
        elif channel == "learning_state" and subject_id is not None:
            candidates = [
                RecallItem(
                    channel=channel,
                    kind="learning_state",
                    id=f"learning:{item.subject_id}:{item.project_id or 'global'}:{item.focus}",
                    summary=f"{item.focus}: {item.status}",
                    confidence=item.mastery,
                    occurred_at=item.updated_at,
                    data={
                        "focus": item.focus,
                        "status": item.status,
                        "mastery": item.mastery,
                        "evidence_count": item.evidence_count,
                        "project_id": item.project_id,
                    },
                )
                for item in store.list_learning_state(
                    subject_id=subject_id, project_id=project_id
                )
            ]
        elif channel == "raw_history" and plan.need_raw_history:
            candidates = [
                RecallItem(
                    channel=channel,
                    kind="raw_event",
                    id=event.id,
                    summary=event.event_type,
                    confidence=1.0,
                    occurred_at=event.occurred_at,
                    data={
                        "actor_id": event.actor_id,
                        "project_id": event.project_id,
                        "payload": event.payload,
                    },
                )
                for event in reversed(store.list_events(project_id=project_id))
            ]
        else:
            candidates = []
        candidates.sort(key=lambda item: _rank_key(item, query), reverse=True)
        gathered.extend(candidates[:limit])
    gathered.sort(key=lambda item: _rank_key(item, query), reverse=True)
    return RecallView(plan=plan, items=tuple(gathered))


def _entity_id(entities: tuple[str, ...], kind: str) -> str | None:
    prefix = f"{kind}:"
    return next((entity[len(prefix):] for entity in entities if entity.startswith(prefix)), None)


def _preference_items(
    store: SQLiteMemoryStore, subject_id: str, project_id: str | None
) -> list[RecallItem]:
    items: list[RecallItem] = []
    for claim, state, policy in store.list_claims(
        subject_id=subject_id,
        claim_type=ClaimType.PREFERENCE,
        status=ClaimStatus.CONFIRMED,
    ):
        if not _policy_allows(policy, subject_id, project_id):
            continue
        items.append(_claim_item("user_preferences", claim, state.confidence))
    return items


def _project_items(store: SQLiteMemoryStore, project_id: str) -> list[RecallItem]:
    items = [
        RecallItem(
            channel="active_project",
            kind="project_state",
            id=f"project-state:{entry.project_id}:{entry.key}",
            summary=f"{entry.key}: {entry.value}",
            confidence=1.0,
            occurred_at=entry.updated_at,
            data={"key": entry.key, "value": entry.value},
        )
        for entry in store.list_project_state(project_id)
    ]
    for claim, state, _policy in store.list_claims(
        subject_id=project_id,
        claim_type=ClaimType.DECISION,
        status=ClaimStatus.CONFIRMED,
    ):
        items.append(_claim_item("active_project", claim, state.confidence))
    return items


def _claim_item(channel: str, claim: MemoryClaim, confidence: float) -> RecallItem:
    data: JsonObject = {
        "subject_type": claim.subject_type,
        "subject_id": claim.subject_id,
        "predicate": claim.predicate,
        "value": claim.value,
        "claim_type": claim.claim_type.value,
        "context_type": claim.context_type,
        "context_id": claim.context_id,
        "tags": list(claim.tags),
    }
    return RecallItem(
        channel=channel,
        kind="claim",
        id=claim.id,
        summary=f"{claim.predicate}: {claim.value}",
        confidence=confidence,
        occurred_at="",
        data=data,
    )


def _policy_allows(
    policy: MemoryPolicy, subject_id: str, project_id: str | None
) -> bool:
    if policy.sensitivity is Sensitivity.QUARANTINE:
        return False
    if policy.visibility == "public":
        return True
    if policy.owner_id in (subject_id, f"person:{subject_id}"):
        return True
    return project_id is not None and f"project:{project_id}" in policy.allowed_contexts


def _rank_key(item: RecallItem, query: str) -> tuple[int, float, str]:
    needle = query.casefold().strip()
    haystack = f"{item.summary} {item.data}".casefold()
    query_match = int(bool(needle) and needle in haystack)
    return query_match, item.confidence, item.occurred_at


__all__ = ["RecallPlanner", "recall"]
