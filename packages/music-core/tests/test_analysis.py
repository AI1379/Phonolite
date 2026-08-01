"""Tests for the analysis layer (design doc issue #4)."""

from __future__ import annotations

import pytest

from music_core.analysis import (
    analyze_bass_contour,
    analyze_density,
    analyze_register,
    inspect,
)
from music_core.ir import (
    MeterEvent,
    NoteEvent,
    Region,
    ScoreDocument,
)


def _note(
    nid: str, pitch: int, onset: float, duration: float, *, track_id: str = "piano"
) -> NoteEvent:
    return NoteEvent(
        id=nid,
        track_id=track_id,
        pitch=pitch,
        onset_beats=onset,
        duration_beats=duration,
        velocity=80,
    )


def _static_doc() -> ScoreDocument:
    """Four 4/4 bars: a static C2 bass (one per bar) + a static melody block.

    The bass is identical every bar and the melody extremes do not move, so
    both register and bass analyses should flag a static/repetitive feeling.
    """
    notes: list[NoteEvent] = []
    # Static bass: C2 every bar.
    for bar in range(4):
        notes.append(_note(f"b{bar}", 36, bar * 4.0, 4.0, track_id="bass"))
    # Static melody block: C4 and G4 sustained every bar (same extremes).
    for bar in range(4):
        notes.append(_note(f"m{bar}a", 60, bar * 4.0, 4.0))
        notes.append(_note(f"m{bar}b", 67, bar * 4.0, 4.0))
    return ScoreDocument(
        id="v",
        ppq=480,
        notes=notes,
        meters=[MeterEvent(beat=0.0, numerator=4, denominator=4)],
    )


def test_register_finding_reports_range_with_full_confidence() -> None:
    findings = analyze_register(_static_doc())
    assert findings, "expected at least one register finding"
    finding = findings[0]
    assert finding.confidence == pytest.approx(1.0)
    evidence = {e.metric: e.value for e in finding.evidence}
    assert evidence["register_range_semitones"] == 31  # 36..67
    assert finding.location.bars == (1, 4)
    assert finding.location.track_ids  # non-empty


def test_register_detects_static_register_across_bars() -> None:
    findings = analyze_register(_static_doc())
    static = [f for f in findings if "static" in f.observation.lower()]
    assert static, "expected a static-register finding"
    assert static[0].confidence < 1.0  # interpretive -> hedged
    assert static[0].alternatives  # carries an alternative explanation


def test_density_reports_note_rate_and_simultaneity() -> None:
    findings = analyze_density(_static_doc())
    assert len(findings) == 1
    evidence = {e.metric: e.value for e in findings[0].evidence}
    # 4 bars * 3 notes/bar = 12 notes over 16 beats.
    assert evidence["note_count"] == 12
    assert evidence["notes_per_beat"] == pytest.approx(0.75, abs=0.01)
    # 3 notes always sounding together.
    assert evidence["average_simultaneous_notes"] == pytest.approx(3.0, abs=0.05)


def test_bass_contour_flags_high_similarity_repetition() -> None:
    findings = analyze_bass_contour(_static_doc())
    assert len(findings) == 1
    finding = findings[0]
    evidence = {e.metric: e.value for e in finding.evidence}
    similarity = evidence["bass_contour_similarity"]
    assert isinstance(similarity, float)
    assert similarity == pytest.approx(1.0)
    assert "repetition" in finding.interpretation.lower()
    assert finding.confidence <= similarity


def test_bass_contour_detects_rising_motion() -> None:
    notes = [
        _note("b0", 36, 0.0, 4.0, track_id="bass"),
        _note("b1", 40, 4.0, 4.0, track_id="bass"),
        _note("b2", 43, 8.0, 4.0, track_id="bass"),
        _note("b3", 48, 12.0, 4.0, track_id="bass"),
    ]
    doc = ScoreDocument(
        id="v", ppq=480, notes=notes,
        meters=[MeterEvent(beat=0.0, numerator=4, denominator=4)],
    )
    findings = analyze_bass_contour(doc)
    assert findings
    assert "rising" in findings[0].interpretation.lower()


def test_inspect_runs_all_three_analyzers() -> None:
    findings = inspect(_static_doc())
    # register (>=1) + density (1) + bass (1)
    assert len(findings) >= 3


def test_analysis_respects_region_scope() -> None:
    doc = _static_doc()
    region = Region(0.0, 4.0)  # only bar 1
    findings = analyze_density(doc, region=region)
    evidence = {e.metric: e.value for e in findings[0].evidence}
    assert evidence["note_count"] == 3  # only the first bar's notes


def test_empty_document_yields_no_findings() -> None:
    doc = ScoreDocument(id="v", ppq=480)
    assert inspect(doc) == []
