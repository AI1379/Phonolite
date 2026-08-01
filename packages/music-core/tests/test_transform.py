"""Tests for controlled transforms (design doc issues #5 and #6)."""

from __future__ import annotations

import pytest

from music_core.ir import MeterEvent, NoteEvent, Region, ScoreDocument
from music_core.transform import (
    TransformRequest,
    apply_transform,
    delay_bass_resolution,
    rhythmic_scaling,
)


def _note(nid: str, pitch: int, onset: float, duration: float, *, track_id: str = "t") -> NoteEvent:
    return NoteEvent(
        id=nid, track_id=track_id, pitch=pitch, onset_beats=onset,
        duration_beats=duration, velocity=80,
    )


def _two_voice_doc() -> ScoreDocument:
    return ScoreDocument(
        id="v001", ppq=480,
        notes=[
            _note("bass", 36, 0.0, 4.0, track_id="bass"),
            _note("melody", 60, 0.0, 4.0, track_id="melody"),
        ],
        meters=[MeterEvent(beat=0.0, numerator=4, denominator=4)],
    )


def _by_id(doc: ScoreDocument) -> dict[str, NoteEvent]:
    return {n.id: n for n in doc.notes}


def test_delayed_bass_shifts_only_bass_and_preserves_ids() -> None:
    doc = _two_voice_doc()
    result = delay_bass_resolution(doc, Region(0.0, 4.0), delay_beats=1.0)

    assert result.operation == "delay_bass_resolution"
    assert result.changed_event_ids == ["bass"]
    assert result.validation is not None

    new = _by_id(result.document)
    assert new["bass"].onset_beats == pytest.approx(1.0)  # moved later
    assert new["bass"].duration_beats == pytest.approx(4.0)  # unchanged
    assert new["melody"].onset_beats == pytest.approx(0.0)  # untouched


def test_transform_does_not_mutate_source() -> None:
    doc = _two_voice_doc()
    before = doc.notes[0].onset_beats
    delay_bass_resolution(doc, Region(0.0, 4.0), delay_beats=1.0)
    # Source document is untouched.
    assert doc.notes[0].onset_beats == before
    assert all(n.id for n in doc.notes)  # ids intact


def test_transform_produces_new_version_on_branch() -> None:
    doc = _two_voice_doc()
    result = delay_bass_resolution(doc, Region(0.0, 4.0), delay_beats=1.0, branch="exp/late")
    assert result.document.id != doc.id  # new version
    assert result.branch == "exp/late"
    assert result.document.metadata["parent_version"] == doc.id


def test_delay_clamps_before_next_bass_onset() -> None:
    doc = ScoreDocument(
        id="v", ppq=480,
        notes=[
            _note("b1", 36, 0.0, 4.0, track_id="bass"),
            _note("b2", 38, 4.0, 4.0, track_id="bass"),
        ],
    )
    result = delay_bass_resolution(doc, Region(0.0, 8.0), delay_beats=5.0)
    new = _by_id(result.document)
    # b1 cannot reach 5.0 because b2 starts at 4.0; clamped just under 4.0.
    assert 0.0 < new["b1"].onset_beats < 4.0
    # b2 is also a bass note: its 5-beat delay clamps to the region end (8.0).
    assert 4.0 < new["b2"].onset_beats < 8.0
    # Order is preserved (the clamp keeps each onset before the next).
    assert new["b1"].onset_beats < new["b2"].onset_beats
    assert any("clamped" in w for w in result.validation.warnings)


def test_augmentation_scales_duration_and_onset() -> None:
    doc = ScoreDocument(
        id="v", ppq=480,
        notes=[_note("a", 60, 0.0, 2.0), _note("b", 62, 2.0, 2.0)],
    )
    result = rhythmic_scaling(doc, Region(0.0, 4.0), factor=2.0)
    new = _by_id(result.document)
    assert new["a"].duration_beats == pytest.approx(4.0)
    assert new["b"].onset_beats == pytest.approx(4.0)
    assert new["b"].duration_beats == pytest.approx(4.0)
    assert sorted(result.changed_event_ids) == ["a", "b"]


def test_diminution_halves() -> None:
    doc = ScoreDocument(
        id="v", ppq=480,
        notes=[_note("a", 60, 0.0, 2.0), _note("b", 62, 2.0, 2.0)],
    )
    result = rhythmic_scaling(doc, Region(0.0, 4.0), factor=0.5)
    new = _by_id(result.document)
    assert new["a"].duration_beats == pytest.approx(1.0)
    assert new["b"].onset_beats == pytest.approx(1.0)


def test_rhythmic_scaling_leaves_outside_region_untouched() -> None:
    doc = ScoreDocument(
        id="v", ppq=480,
        notes=[_note("in", 60, 1.0, 1.0), _note("out", 62, 10.0, 1.0)],
    )
    result = rhythmic_scaling(doc, Region(0.0, 4.0), factor=2.0)
    new = _by_id(result.document)
    assert new["out"].onset_beats == pytest.approx(10.0)
    assert result.changed_event_ids == ["in"]


def test_invalid_factors_rejected() -> None:
    doc = _two_voice_doc()
    with pytest.raises(ValueError):
        rhythmic_scaling(doc, Region(0.0, 4.0), factor=1.0)
    with pytest.raises(ValueError):
        rhythmic_scaling(doc, Region(0.0, 4.0), factor=0.0)
    with pytest.raises(ValueError):
        delay_bass_resolution(doc, Region(0.0, 4.0), delay_beats=-1.0)


def test_apply_transform_dispatches_via_request() -> None:
    doc = _two_voice_doc()
    request = TransformRequest(
        source_version_id=doc.id,
        region=Region(0.0, 4.0),
        operation="delay_bass_resolution",
        parameters={"delay_beats": 1.0},
        preserve=[],
        vary=["bass_onset"],
        output_branch="exp/late",
    )
    result = apply_transform(doc, request)
    assert result.branch == "exp/late"
    assert result.changed_event_ids == ["bass"]


def test_unknown_operation_raises() -> None:
    doc = _two_voice_doc()
    request = TransformRequest(
        source_version_id=doc.id,
        region=Region(0.0, 4.0),
        operation="nope",
        parameters={},
        preserve=[],
        vary=[],
        output_branch="x",
    )
    with pytest.raises(ValueError):
        apply_transform(doc, request)
