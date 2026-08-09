"""Pydantic v2 request models for the Domain API (design doc section 8).

These models only validate the HTTP boundary: they parse JSON bodies into
typed objects and turn ``Region``-like params into ``music_core.ir.Region``.
All musical work stays in ``music_core``; nothing here computes a result.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

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
