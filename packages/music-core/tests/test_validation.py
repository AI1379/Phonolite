"""Tests for deterministic score validation (design doc section 7.4)."""

from __future__ import annotations

from music_core.ir import NoteEvent, ScoreDocument
from music_core.validation import validate_document, validate_region


def _doc(notes: list[NoteEvent]) -> ScoreDocument:
    return ScoreDocument(id="v", ppq=480, notes=notes)


def test_valid_document_has_no_errors() -> None:
    doc = _doc(
        [
            NoteEvent(id="n1", track_id="t", pitch=60, onset_beats=0.0, duration_beats=1.0, velocity=80),
            NoteEvent(id="n2", track_id="t", pitch=64, onset_beats=1.0, duration_beats=1.0, velocity=80),
        ]
    )
    report = validate_document(doc)
    assert report.ok
    assert report.errors == []


def test_out_of_range_pitch_and_negative_onset_are_errors() -> None:
    doc = _doc(
        [
            NoteEvent(id="bad", track_id="t", pitch=200, onset_beats=-1.0, duration_beats=1.0, velocity=80),
        ]
    )
    report = validate_document(doc)
    assert not report.ok
    assert any("out of MIDI range" in e for e in report.errors)
    assert any("negative onset" in e for e in report.errors)


def test_overlapping_same_pitch_warns() -> None:
    doc = _doc(
        [
            NoteEvent(id="a", track_id="t", pitch=60, onset_beats=0.0, duration_beats=2.0, velocity=80, channel=0),
            NoteEvent(id="b", track_id="t", pitch=60, onset_beats=1.0, duration_beats=1.0, velocity=80, channel=0),
        ]
    )
    report = validate_document(doc)
    assert report.ok  # warnings, not errors
    assert any("overlapping same-pitch" in w for w in report.warnings)


def test_wide_simultaneous_span_warns() -> None:
    doc = _doc(
        [
            NoteEvent(id="a", track_id="t", pitch=36, onset_beats=0.0, duration_beats=2.0, velocity=80, channel=0),
            NoteEvent(id="b", track_id="t", pitch=84, onset_beats=0.0, duration_beats=2.0, velocity=80, channel=0),
        ]
    )
    report = validate_document(doc)
    assert any("span" in w for w in report.warnings)


def test_validate_region_scopes_to_span() -> None:
    from music_core.ir import Region

    notes = [
        NoteEvent(id="in", track_id="t", pitch=60, onset_beats=2.0, duration_beats=1.0, velocity=80),
        NoteEvent(id="out", track_id="t", pitch=999, onset_beats=10.0, duration_beats=1.0, velocity=80),
    ]
    report = validate_region(_doc(notes), region=Region(0.0, 5.0))
    assert report.ok  # the bad note is outside the region
