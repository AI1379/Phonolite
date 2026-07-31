"""Unified Score IR (design doc section 7.1).

Conventions:
  - Internal time is always in beats (quarter notes), never in MIDI ticks
    or seconds; ``ppq`` records the resolution of the import source so
    ``source_ref`` mappings can round-trip.
  - Pitch is always a MIDI note number. Pitch spelling, key, and tonal
    analysis are *projections* produced by the analysis layer — they must
    not replace the raw MIDI pitch here.
  - Every event carries a stable ``id`` so that diffs, analyses, and
    experiments can refer to it across versions. IDs are minted once at
    import/creation time and never recycled.
  - Transforms never mutate a document in place; they produce a new
    ``ScoreDocument`` on a new branch (design doc section 7.1, 14.2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


type MetadataValue = (
    str
    | int
    | float
    | bool
    | None
    | list[MetadataValue]
    | dict[str, MetadataValue]
)


def new_event_id(prefix: str) -> str:
    """Mint a stable, unique event ID, e.g. ``note_3f2a9c1d...``."""
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass
class NoteEvent:
    """A single sounding note, voice-leading agnostic.

    ``source_ref`` points back to the origin (e.g. a MusicXML measure/offset
    or a MIDI tick position) so imported material stays traceable.
    """

    id: str
    track_id: str
    pitch: int
    onset_beats: float
    duration_beats: float
    velocity: int
    voice_id: str | None = None
    channel: int | None = None
    articulations: list[str] = field(default_factory=list)
    source_ref: str | None = None

    @property
    def offset_beats(self) -> float:
        """Beat position at which the note stops sounding."""
        return self.onset_beats + self.duration_beats


@dataclass
class TempoEvent:
    beat: float
    bpm: float


@dataclass
class MeterEvent:
    beat: float
    numerator: int
    denominator: int


@dataclass
class ScoreDocument:
    """A versioned score: the unit that analyses and transforms operate on."""

    id: str
    ppq: int
    notes: list[NoteEvent] = field(default_factory=list)
    tempos: list[TempoEvent] = field(default_factory=list)
    meters: list[MeterEvent] = field(default_factory=list)
    markers: list[dict[str, MetadataValue]] = field(default_factory=list)
    metadata: dict[str, MetadataValue] = field(default_factory=dict)

    @property
    def duration_beats(self) -> float:
        """End of the last sounding note, in beats (0.0 for an empty score)."""
        if not self.notes:
            return 0.0
        return max(note.offset_beats for note in self.notes)
