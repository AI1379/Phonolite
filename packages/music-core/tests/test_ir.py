"""Tests for the Score IR skeleton (design doc section 7.1)."""

from __future__ import annotations

import dataclasses

from music_core import MeterEvent, NoteEvent, ScoreDocument, TempoEvent
from music_core.ir import new_event_id


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
