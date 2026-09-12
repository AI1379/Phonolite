"""Explicit, bounded alignment between reference audio seconds and score beats."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class AlignmentAnchor:
    seconds: float
    beat: float


@dataclass(frozen=True)
class ScoreReference:
    asset_id: str
    anchors: tuple[AlignmentAnchor, ...]

    def __post_init__(self) -> None:
        if not self.asset_id or not 2 <= len(self.anchors) <= 64:
            raise ValueError("alignment requires an asset and 2 to 64 anchors")
        for anchor in self.anchors:
            if not all(math.isfinite(value) and value >= 0 for value in (anchor.seconds, anchor.beat)):
                raise ValueError("alignment seconds and beats must be finite and non-negative")
        for left, right in zip(self.anchors, self.anchors[1:]):
            if right.seconds <= left.seconds or right.beat <= left.beat:
                raise ValueError("alignment seconds and beats must both increase strictly")
            bpm = 60 * (right.beat - left.beat) / (right.seconds - left.seconds)
            if not 10 <= bpm <= 600:
                raise ValueError("each alignment segment must imply 10 to 600 BPM")


@dataclass(frozen=True)
class NoteEvidence:
    asset_id: str
    start_seconds: float
    end_seconds: float
    method: str = "manual_alignment"


def reference_seconds(reference: ScoreReference, beat: float) -> float | None:
    """Interpolate inside marked anchors; never invent alignment outside them."""
    for left, right in zip(reference.anchors, reference.anchors[1:]):
        if left.beat <= beat <= right.beat:
            return left.seconds + (beat - left.beat) * (right.seconds - left.seconds) / (right.beat - left.beat)
    return None


def reference_beat(reference: ScoreReference, seconds: float) -> float | None:
    for left, right in zip(reference.anchors, reference.anchors[1:]):
        if left.seconds <= seconds <= right.seconds:
            return left.beat + (seconds - left.seconds) * (right.beat - left.beat) / (right.seconds - left.seconds)
    return None
