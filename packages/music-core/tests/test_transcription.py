"""Reference alignment, provenance and immutable manual transcription revisions."""

from __future__ import annotations

import pytest

from music_core.edit import NoteValues, align_score, create_draft, edit_note
from music_core.io.midi import dumps_midi, loads_midi
from music_core.reference import AlignmentAnchor, ScoreReference, reference_beat, reference_seconds


def _reference() -> ScoreReference:
    return ScoreReference("audio-one", (AlignmentAnchor(2, 0), AlignmentAnchor(6, 8), AlignmentAnchor(10, 12)))


def test_alignment_preserves_audio_offset_and_variable_tempo_without_extrapolation() -> None:
    ref = _reference()
    assert reference_seconds(ref, 4) == 4
    assert reference_seconds(ref, 10) == 8
    assert reference_beat(ref, 8) == 10
    assert reference_seconds(ref, 13) is None
    assert reference_beat(ref, 1) is None
    doc = create_draft(title="draft", reference=ref)
    assert [(tempo.beat, tempo.bpm) for tempo in doc.tempos] == [(0, 120), (8, 60)]
    assert doc.duration_beats == 12
    assert loads_midi(dumps_midi(doc)).duration_beats == 12


@pytest.mark.parametrize("anchors", [
    (AlignmentAnchor(2, 0), AlignmentAnchor(1, 8)),
    (AlignmentAnchor(1, 0), AlignmentAnchor(2, 0)),
    (AlignmentAnchor(float("nan"), 0), AlignmentAnchor(2, 8)),
    (AlignmentAnchor(0, 0), AlignmentAnchor(0.01, 8)),
])
def test_invalid_alignment_is_rejected(anchors: tuple[AlignmentAnchor, ...]) -> None:
    with pytest.raises(ValueError):
        ScoreReference("ref", anchors)


def test_add_correct_confirm_remove_keep_versions_and_evidence() -> None:
    original = create_draft(title="draft", reference=_reference())
    added = edit_note(original, action="add", values=NoteValues(60, 2, 1))
    assert original.notes == []
    note = added.notes[0]
    assert note.transcription_status == "uncertain"
    assert note.reference_evidence is not None
    assert (note.reference_evidence.start_seconds, note.reference_evidence.end_seconds) == (3, 3.5)
    corrected = edit_note(added, action="update", note_id=note.id,
                          values=NoteValues(62, 2.5, 0.5, role="bass", transcription_status="confirmed"))
    assert corrected.notes[0].id == note.id
    assert corrected.notes[0].pitch == 62
    assert corrected.notes[0].transcription_status == "confirmed"
    assert added.notes[0].pitch == 60
    removed = edit_note(corrected, action="remove", note_id=note.id)
    assert removed.notes == []
    assert corrected.notes
    assert len({original.id, added.id, corrected.id, removed.id}) == 4
    assert removed.duration_beats == 12


def test_unaligned_notes_have_no_fabricated_audio_evidence() -> None:
    doc = create_draft(title="draft", reference=_reference())
    revised = edit_note(doc, action="add", values=NoteValues(60, 12, 1))
    assert revised.notes[0].reference_evidence is None
    with pytest.raises(ValueError, match="exist"):
        edit_note(doc, action="remove", note_id="missing")


def test_realigning_to_new_evidence_requires_review_again() -> None:
    source = edit_note(create_draft(title="draft", reference=_reference()), action="add",
                       values=NoteValues(60, 0, 1, transcription_status="confirmed"))
    ref = ScoreReference("audio-two", (AlignmentAnchor(1, 0), AlignmentAnchor(9, 16)))
    result = align_score(source, ref)
    assert source.notes[0].transcription_status == "confirmed"
    assert result.notes[0].transcription_status == "uncertain"
    assert result.notes[0].pitch == source.notes[0].pitch
    assert result.notes[0].reference_evidence is not None
    assert result.notes[0].reference_evidence.asset_id == "audio-two"
