"""Pydantic v2 request models for the Domain API (design doc section 8).

These models only validate the HTTP boundary: they parse JSON bodies into
typed objects and turn ``Region``-like params into ``music_core.ir.Region``.
All musical work stays in ``music_core``; nothing here computes a result.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from memory_core import ClaimType, JsonValue
from music_core.ir import Region


class RegionParams(BaseModel):
    """A region posted by the client, in beats with optional track/voice scope."""

    start_beat: float
    end_beat: float
    track_ids: list[str] | None = None
    voice_ids: list[str] | None = None

    def to_region(self) -> Region:
        """Build the corresponding :class:`music_core.ir.Region`."""
        return Region(
            start_beat=self.start_beat,
            end_beat=self.end_beat,
            track_ids=tuple(self.track_ids) if self.track_ids is not None else None,
            voice_ids=tuple(self.voice_ids) if self.voice_ids is not None else None,
        )


class ImportRequest(BaseModel):
    """Import a MIDI file carried as base64 (so it travels in a JSON body)."""

    midi_b64: str = Field(..., description="Standard MIDI file bytes, base64-encoded")
    project_id: str | None = None
    title: str | None = None


class CompareRequest(BaseModel):
    """Compare two stored versions by stable note ID."""

    before_version_id: str
    after_version_id: str


class TransformRequestModel(BaseModel):
    """Apply a controlled transform, producing a new stored version."""

    source_version_id: str
    region: RegionParams
    operation: str
    parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    output_branch: str | None = None
    preserve: list[str] = Field(default_factory=list)
    vary: list[str] = Field(default_factory=list)


class GoalUpdateRequest(BaseModel):
    """Set the project goal (the slice's "Project Goal" step)."""

    description: str
    bars: tuple[int, int] | None = None
    beats: tuple[float, float] | None = None


class DecisionRequest(BaseModel):
    """Record an explicit project decision (``project_record_decision``)."""

    summary: str
    chosen_version_id: str | None = None
    reason: str | None = None
    tags: list[str] = Field(default_factory=list)


class AcceptRequest(BaseModel):
    """Promote a variant to the active version (``project_accept_variant``)."""

    version_id: str


class ChooseRequest(BaseModel):
    """A/B selection: record a decision and accept the chosen variant.

    The reason doubles as the lightweight "learning event" of the first
    vertical slice — the user states why this variant was better, which is the
    seed of later (MVP-2) structured learning state.
    """

    chosen_version_id: str
    reason: str | None = None
    tags: list[str] = Field(default_factory=list)
    experiment_id: str | None = None
    subject_id: str = "user"
    learning_focus: str | None = None


class MemoryEpisodeRequest(BaseModel):
    """Record an immutable episode and its low-inference observation."""

    actor_id: str = "person:user"
    project_id: str | None = None
    summary: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class MemoryClaimRequest(BaseModel):
    """Propose a typed claim; proposals are never implicitly confirmed."""

    actor_id: str = "person:user"
    project_id: str | None = None
    subject_type: str
    subject_id: str
    predicate: str
    value: dict[str, JsonValue]
    claim_type: ClaimType
    context_type: str | None = None
    context_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    excerpt: str | None = None
    sensitivity: str = "private"
    visibility: str = "private"
    allowed_contexts: list[str] = Field(default_factory=list)


class ClaimConfirmRequest(BaseModel):
    """Explicit approval required to promote a claim to confirmed."""

    actor_id: str = "person:user"


class MemoryQueryRequest(BaseModel):
    """Inputs for Recall Planner and channel-aware memory retrieval."""

    query: str = ""
    project_id: str | None = None
    subject_id: str | None = "user"
    need_raw_history: bool = False
    time_horizon: str = "long"
    per_channel_limit: int = Field(default=5, ge=1, le=50)


class LearningOutcomeRequest(BaseModel):
    """Record evidence-backed learning state explicitly."""

    actor_id: str = "person:user"
    subject_id: str = "user"
    project_id: str | None = None
    focus: str
    status: str
    mastery: float = Field(ge=0.0, le=1.0)
    evidence: str | None = None


class AgentTaskRequest(BaseModel):
    """Delegate a new task to one of the three Workbench agent modes."""

    prompt: str = Field(min_length=1)
    mode: Literal["analyze", "learn", "experiment"] = "analyze"
    session_id: str | None = None


class AgentResumeRequest(BaseModel):
    """Continue an existing OpenCode session in a selected Workbench mode."""

    prompt: str = Field(min_length=1)
    mode: Literal["analyze", "learn", "experiment"] = "analyze"
