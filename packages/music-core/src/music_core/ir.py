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


@dataclass(frozen=True)
class Region:
    """A time span in beats, optionally restricted to tracks/voices.

    ``track_ids`` / ``voice_ids`` of ``None`` means "no restriction". Time is
    half-open ``[start_beat, end_beat)``. Build from bar numbers with
    :func:`region_from_bars` using a beats-per-bar value derived from a meter.
    """

    start_beat: float
    end_beat: float
    track_ids: tuple[str, ...] | None = None
    voice_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.start_beat < 0.0 or self.end_beat < self.start_beat:
            raise ValueError(
                f"Region must satisfy 0 <= start <= end, got "
                f"[{self.start_beat}, {self.end_beat})"
            )


def meter_beats_per_bar(meter: MeterEvent) -> float:
    """Quarter-note beats in one bar of ``meter``.

    The IR keeps time in quarter-note beats regardless of meter denominator,
    so a 4/4 bar is 4 beats and a 9/8 bar is 4.5 beats (9 eighths).
    """
    if meter.denominator <= 0:
        raise ValueError(
            f"Meter denominator must be positive, got {meter.denominator}"
        )
    return meter.numerator * 4.0 / meter.denominator


def region_from_bars(
    bar_start: int,
    bar_end: int,
    beats_per_bar: float,
    *,
    start_beat_offset: float = 0.0,
    track_ids: tuple[str, ...] | None = None,
    voice_ids: tuple[str, ...] | None = None,
) -> Region:
    """Build a Region covering bars ``[bar_start, bar_end]`` (1-indexed, inclusive).

    ``start_beat_offset`` is the beat at which bar 1 begins (usually 0.0,
    but non-zero when a region is measured against a meter change mid-score).
    """
    if bar_start < 1 or bar_end < bar_start:
        raise ValueError(
            f"Need 1 <= bar_start <= bar_end, got bar_start={bar_start}, "
            f"bar_end={bar_end}"
        )
    if beats_per_bar <= 0.0:
        raise ValueError(f"beats_per_bar must be positive, got {beats_per_bar}")
    start = start_beat_offset + (bar_start - 1) * beats_per_bar
    end = start_beat_offset + bar_end * beats_per_bar
    return Region(start, end, track_ids=track_ids, voice_ids=voice_ids)


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

    def select_region(self, region: Region) -> list[NoteEvent]:
        """Notes overlapping ``region`` (half-open), filtered by tracks/voices.

        A note is included when it *sounds at all* inside the span, i.e. its
        onset is before the region end and its offset is after the region
        start. Notes whose duration is zero are treated as sounding at their
        onset only. Result is sorted by ``(onset, pitch)`` for stable output.
        """
        selected: list[NoteEvent] = []
        for note in self.notes:
            if region.track_ids is not None and note.track_id not in region.track_ids:
                continue
            if region.voice_ids is not None and (
                note.voice_id is None or note.voice_id not in region.voice_ids
            ):
                continue
            offset = note.offset_beats if note.duration_beats > 0.0 else note.onset_beats
            if note.onset_beats < region.end_beat and offset > region.start_beat:
                selected.append(note)
        selected.sort(key=lambda n: (n.onset_beats, n.pitch))
        return selected


def beat_to_bar(beat: float, beats_per_bar: float) -> int:
    """1-indexed bar number containing ``beat`` (bar 1 starts at beat 0)."""
    if beats_per_bar <= 0.0:
        raise ValueError(f"beats_per_bar must be positive, got {beats_per_bar}")
    return int(beat // beats_per_bar) + 1
