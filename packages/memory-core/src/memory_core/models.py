"""Typed memory records shared by storage, recall, and application layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


class ClaimType(StrEnum):
    """The fixed coarse claim taxonomy from design section 11.5."""

    FACT = "fact"
    PREFERENCE = "preference"
    GOAL = "goal"
    CONSTRAINT = "constraint"
    DECISION = "decision"
    RELATIONSHIP = "relationship"
    PROCEDURE = "procedure"
    SKILL = "skill"
    ARTIFACT_STATE = "artifact_state"


class ClaimStatus(StrEnum):
    """Lifecycle states allowed for a claim."""

    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    WEAKENED = "weakened"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    CONTEXT_LIMITED = "context_limited"
    REJECTED = "rejected"


class Sensitivity(StrEnum):
    """Storage sensitivity; unknown input is quarantined by the store."""

    PRIVATE = "private"
    SENSITIVE = "sensitive"
    PUBLIC = "public"
    QUARANTINE = "quarantine"


@dataclass(frozen=True)
class MemoryEvent:
    """An immutable fact that entered the memory pipeline."""

    id: str
    event_type: str
    actor_id: str
    project_id: str | None
    payload: JsonObject
    occurred_at: str


@dataclass(frozen=True)
class Observation:
    """A low-inference description projected from a raw event."""

    id: str
    source_event_id: str
    subject: str
    event: str
    context: str | None
    confidence: float
    observed_at: str
    project_id: str | None


@dataclass(frozen=True)
class MemoryClaim:
    """A typed proposition kept separate from evidence and lifecycle state."""

    id: str
    subject_type: str
    subject_id: str
    predicate: str
    value: JsonObject
    context_type: str | None
    context_id: str | None
    claim_type: ClaimType
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimEvidence:
    """Trace from a claim back to its immutable source event."""

    claim_id: str
    event_id: str
    excerpt: str | None
    extractor: str
    weight: float
    observed_at: str


@dataclass(frozen=True)
class ClaimState:
    """Mutable lifecycle projection for an immutable claim proposition."""

    claim_id: str
    status: ClaimStatus
    confidence: float
    valid_from: str | None
    valid_until: str | None
    superseded_by: str | None
    last_confirmed_at: str | None


@dataclass(frozen=True)
class MemoryPolicy:
    """Ownership and visibility controls evaluated independently of tags."""

    claim_id: str
    owner_id: str
    visibility: str
    sensitivity: Sensitivity
    allowed_contexts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectStateEntry:
    """An explicit current-state projection scoped to one project."""

    project_id: str
    key: str
    value: JsonValue
    source_event_id: str
    updated_at: str


@dataclass(frozen=True)
class LearningState:
    """Current evidence-backed learning state for one subject and focus."""

    subject_id: str
    project_id: str | None
    focus: str
    status: str
    mastery: float
    evidence_count: int
    source_event_id: str
    updated_at: str


@dataclass(frozen=True)
class RecallPlan:
    """Channel-specific retrieval plan produced before querying memory."""

    channels: tuple[str, ...]
    entities: tuple[str, ...]
    time_horizon: str
    need_raw_history: bool
    channel_limits: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RecallItem:
    """A ranked, display-safe item returned by one recall channel."""

    channel: str
    kind: str
    id: str
    summary: str
    confidence: float
    occurred_at: str
    data: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class RecallView:
    """Recall result retaining its plan and per-channel provenance."""

    plan: RecallPlan
    items: tuple[RecallItem, ...]


@dataclass(frozen=True)
class ExperimentOutcome:
    """Explicit user outcome projected into several logical memory stores."""

    project_id: str
    subject_id: str
    experiment_id: str
    chosen_version_id: str
    reason: str | None
    learning_focus: str | None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class OutcomeProjection:
    """Identifiers created while projecting an experiment outcome."""

    event: MemoryEvent
    observation_id: str
    decision_claim_id: str
    preference_claim_id: str | None
    learning_focus: str | None


__all__ = [
    "ClaimEvidence",
    "ClaimState",
    "ClaimStatus",
    "ClaimType",
    "ExperimentOutcome",
    "JsonObject",
    "JsonValue",
    "LearningState",
    "MemoryClaim",
    "MemoryEvent",
    "MemoryPolicy",
    "Observation",
    "OutcomeProjection",
    "ProjectStateEntry",
    "RecallItem",
    "RecallPlan",
    "RecallView",
    "Sensitivity",
]
