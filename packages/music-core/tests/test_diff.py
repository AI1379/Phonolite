"""Tests for semantic score diff (design doc issue #7)."""

from __future__ import annotations

from music_core.diff import diff
from music_core.ir import NoteEvent, Region, ScoreDocument
from music_core.transform import delay_bass_resolution


def _note(nid: str, pitch: int, onset: float, duration: float) -> NoteEvent:
    return NoteEvent(
        id=nid, track_id="t", pitch=pitch, onset_beats=onset,
        duration_beats=duration, velocity=80,
    )


def _doc(notes: list[NoteEvent]) -> ScoreDocument:
    return ScoreDocument(id="v", ppq=480, notes=notes)


def test_diff_reports_moved_and_resized() -> None:
    before = _doc([_note("n1", 60, 0.0, 2.0), _note("n2", 64, 2.0, 2.0)])
    after = _doc(
        [
            _note("n1", 60, 1.0, 2.0),   # moved (onset only)
            _note("n2", 64, 2.0, 1.0),   # resized (duration only)
        ]
    )
    d = diff(before, after)
    kinds = {c.note_id: c.kind for c in d.modified}
    assert kinds == {"n1": "moved", "n2": "resized"}
    moved = next(c for c in d.modified if c.note_id == "n1")
    assert moved.field_changes["onset_beats"] == (0.0, 1.0)
    assert "pitch" not in moved.field_changes
    assert d.unchanged_count == 0


def test_diff_reports_added_and_removed() -> None:
    before = _doc([_note("a", 60, 0.0, 1.0)])
    after = _doc([_note("a", 60, 0.0, 1.0), _note("b", 64, 1.0, 1.0)])
    d = diff(before, after)
    assert [c.note_id for c in d.added] == ["b"]
    assert d.unchanged_count == 1

    d2 = diff(after, before)
    assert [c.note_id for c in d2.removed] == ["b"]


def test_diff_is_empty_for_identical_versions() -> None:
    before = _doc([_note("a", 60, 0.0, 1.0)])
    after = _doc([_note("a", 60, 0.0, 1.0)])
    d = diff(before, after)
    assert d.is_empty
    assert d.unchanged_count == 1
    assert "1 unchanged" in d.summary


def test_diff_ignores_sub_quantise_float_drift() -> None:
    before = _doc([_note("a", 60, 0.0, 1.0)])
    after = _doc([_note("a", 60, 0.0 + 1e-9, 1.0 + 1e-9)])
    d = diff(before, after)
    assert d.modified == []
    assert d.unchanged_count == 1


def test_moved_resized_combined_kind() -> None:
    before = _doc([_note("a", 60, 0.0, 2.0)])
    after = _doc([_note("a", 60, 1.0, 1.0)])  # both onset and duration
    d = diff(before, after)
    assert d.modified[0].kind == "moved_resized"


def test_diff_describes_a_real_transform() -> None:
    # Integration: diff the output of delay_bass_resolution against its source.
    doc = _doc(
        [
            _note("bass", 36, 0.0, 4.0),
            _note("melody", 60, 0.0, 4.0),
        ]
    )
    result = delay_bass_resolution(doc, Region(0.0, 4.0), delay_beats=1.0)
    d = diff(doc, result.document)
    kinds = {c.note_id: c.kind for c in d.modified}
    assert kinds == {"bass": "moved"}  # only the bass moved
    assert d.unchanged_count == 1  # melody unchanged
    assert "1 moved" in d.summary
