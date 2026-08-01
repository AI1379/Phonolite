"""Tests for the Score IR skeleton (design doc section 7.1)."""

from __future__ import annotations

import dataclasses

import pytest

from music_core import MeterEvent, NoteEvent, ScoreDocument, TempoEvent
from music_core.ir import (
    Region,
    beat_to_bar,
    meter_beats_per_bar,
    new_event_id,
    region_from_bars,
)


def make_note(pitch: int, onset: float, duration: float) -> NoteEvent:
    return NoteEvent(
        id=new_event_id("note"),
        track_id="piano",
        pitch=pitch,
        onset_beats=onset,
        duration_beats=duration,
        velocity=80,
    )


def test_event_ids_are_unique_and_prefixed() -> None:
    a, b = new_event_id("note"), new_event_id("note")
    assert a != b
    assert a.startswith("note_")


def test_empty_document_has_zero_duration() -> None:
    doc = ScoreDocument(id="v001", ppq=480)
    assert doc.duration_beats == 0.0


def test_duration_beats_covers_last_note_offset() -> None:
    doc = ScoreDocument(
        id="v001",
        ppq=480,
        notes=[make_note(60, 0.0, 1.0), make_note(64, 1.0, 2.5)],
    )
    assert doc.duration_beats == 3.5


def test_note_offset_is_onset_plus_duration() -> None:
    note = make_note(60, 2.0, 0.75)
    assert note.offset_beats == 2.75


def test_default_collections_are_not_shared_between_instances() -> None:
    a, b = ScoreDocument(id="a", ppq=480), ScoreDocument(id="b", ppq=480)
    a.notes.append(make_note(60, 0.0, 1.0))
    assert b.notes == []


def test_asdict_round_trip_preserves_events() -> None:
    doc = ScoreDocument(
        id="v001",
        ppq=480,
        notes=[make_note(60, 0.0, 1.0)],
        tempos=[TempoEvent(beat=0.0, bpm=72.0)],
        meters=[MeterEvent(beat=0.0, numerator=9, denominator=8)],
        metadata={"title": "Lake Tower"},
    )
    data = dataclasses.asdict(doc)
    rebuilt = ScoreDocument(
        id=data["id"],
        ppq=data["ppq"],
        notes=[NoteEvent(**n) for n in data["notes"]],
        tempos=[TempoEvent(**t) for t in data["tempos"]],
        meters=[MeterEvent(**m) for m in data["meters"]],
        markers=data["markers"],
        metadata=data["metadata"],
    )
    assert rebuilt == doc


def test_meter_beats_per_bar_handles_compound_meters() -> None:
    assert meter_beats_per_bar(MeterEvent(beat=0.0, numerator=4, denominator=4)) == 4.0
    assert meter_beats_per_bar(MeterEvent(beat=0.0, numerator=9, denominator=8)) == 4.5
    assert meter_beats_per_bar(MeterEvent(beat=0.0, numerator=3, denominator=8)) == 1.5


def test_meter_beats_per_bar_rejects_zero_denominator() -> None:
    with pytest.raises(ValueError):
        meter_beats_per_bar(MeterEvent(beat=0.0, numerator=4, denominator=0))


def test_beat_to_bar_is_one_indexed() -> None:
    assert beat_to_bar(0.0, 4.0) == 1
    assert beat_to_bar(3.99, 4.0) == 1
    assert beat_to_bar(4.0, 4.0) == 2
    assert beat_to_bar(9.0, 4.5) == 3


def test_region_from_bars_inclusive_span() -> None:
    # Bars 9-16 in 4/4 cover beats [32, 64): 8 bars starting at bar 9.
    region = region_from_bars(9, 16, 4.0)
    assert region.start_beat == 32.0
    assert region.end_beat == 64.0
    assert region.track_ids is None


def test_region_from_bars_rejects_bad_bounds() -> None:
    with pytest.raises(ValueError):
        region_from_bars(0, 4, 4.0)
    with pytest.raises(ValueError):
        region_from_bars(4, 3, 4.0)


def test_region_rejects_inverted_span() -> None:
    with pytest.raises(ValueError):
        Region(5.0, 2.0)


def test_select_region_includes_overlapping_notes_only() -> None:
    notes = [
        make_note(60, 0.0, 2.0),   # fully inside [1,4)
        make_note(62, 1.5, 4.0),   # overlaps, ends at boundary
        make_note(64, 3.9, 1.0),   # starts just before end -> overlaps
        make_note(65, 4.0, 1.0),   # starts at boundary -> excluded (half-open)
        make_note(67, -1.0, 0.5),  # ends before start -> excluded
    ]
    doc = ScoreDocument(id="v", ppq=480, notes=notes)
    selected = doc.select_region(Region(1.0, 4.0))
    pitches = [n.pitch for n in selected]
    assert pitches == [60, 62, 64]


def test_select_region_filters_by_track() -> None:
    notes = [
        NoteEvent(id="a", track_id="piano", pitch=60, onset_beats=0.0, duration_beats=2.0, velocity=80),
        NoteEvent(id="b", track_id="bass", pitch=36, onset_beats=0.0, duration_beats=2.0, velocity=80),
    ]
    doc = ScoreDocument(id="v", ppq=480, notes=notes)
    selected = doc.select_region(Region(0.0, 2.0, track_ids=("bass",)))
    assert [n.id for n in selected] == ["b"]


def test_select_region_is_sorted_and_read_only() -> None:
    notes = [
        make_note(64, 1.0, 1.0),
        make_note(60, 1.0, 1.0),
        make_note(62, 0.5, 1.0),
    ]
    doc = ScoreDocument(id="v", ppq=480, notes=notes)
    selected = doc.select_region(Region(0.0, 2.0))
    assert [(n.onset_beats, n.pitch) for n in selected] == [
        (0.5, 62),
        (1.0, 60),
        (1.0, 64),
    ]
    # The source document's note list is untouched.
    assert len(doc.notes) == 3
