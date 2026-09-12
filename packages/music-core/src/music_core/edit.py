"""Manual transcription drafts and immutable, single-note revisions."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Literal

from music_core.ir import MeterEvent, NoteEvent, ScoreDocument, TempoEvent, new_event_id
from music_core.reference import NoteEvidence, ScoreReference, reference_seconds


@dataclass(frozen=True)
class NoteValues:
    pitch: int
    onset_beats: float
    duration_beats: float
    velocity: int = 80
    track_id: str = "melody"
    role: Literal["melody", "bass", "inner", "unknown"] = "melody"
    transcription_status: Literal["uncertain", "confirmed"] = "uncertain"

    def __post_init__(self) -> None:
        if not 0 <= self.pitch <= 127 or not 1 <= self.velocity <= 127:
            raise ValueError("pitch must be 0..127 and velocity 1..127")
        if not all(math.isfinite(value) for value in (self.onset_beats, self.duration_beats)):
            raise ValueError("note timing must be finite")
        if self.onset_beats < 0 or self.duration_beats <= 0 or self.onset_beats + self.duration_beats > 4096:
            raise ValueError("note must have positive duration and fit inside 0..4096 beats")
        if not self.track_id.strip():
            raise ValueError("track_id cannot be blank")


def create_draft(
    *, title: str, length_beats: float = 32, bpm: float = 80,
    numerator: int = 4, denominator: int = 4, reference: ScoreReference | None = None,
) -> ScoreDocument:
    if not math.isfinite(length_beats) or not 1 <= length_beats <= 4096:
        raise ValueError("draft length must be 1..4096 beats")
    if not math.isfinite(bpm) or not 10 <= bpm <= 600:
        raise ValueError("draft tempo must be 10..600 BPM")
    if not 1 <= numerator <= 32 or denominator not in (1, 2, 4, 8, 16, 32):
        raise ValueError("invalid draft meter")
    tempos = [TempoEvent(0, bpm)]
    if reference is not None:
        if reference.anchors[0].beat != 0:
            raise ValueError("a new reference draft must align its beat 0 to a marked audio time")
        length_beats = reference.anchors[-1].beat
        if not 1 <= length_beats <= 4096:
            raise ValueError("aligned draft must span 1..4096 beats")
        tempos = [TempoEvent(left.beat, 60 * (right.beat - left.beat) / (right.seconds - left.seconds))
                  for left, right in zip(reference.anchors, reference.anchors[1:])]
    return ScoreDocument(new_event_id("score"), 480, tempos=tempos,
                         meters=[MeterEvent(0, numerator, denominator)],
                         metadata={"kind": "transcription", "title": title, "branch": "draft"},
                         length_beats=length_beats, reference=reference)


def edit_note(
    doc: ScoreDocument, *, action: Literal["add", "update", "remove"],
    note_id: str | None = None, values: NoteValues | None = None,
) -> ScoreDocument:
    original = next((note for note in doc.notes if note.id == note_id), None)
    if action != "add" and original is None:
        raise ValueError("the selected note does not exist in this source version")
    if action != "remove" and values is None:
        raise ValueError("note values are required")
    result = copy.deepcopy(doc)
    result.id = new_event_id("score")
    result.metadata.update({"parent_version": doc.id, "branch": "draft/edit", "edit_action": action, "edit_actor": "person:user"})
    if action == "remove":
        result.notes = [note for note in result.notes if note.id != note_id]
        return result
    assert values is not None
    if action == "add":
        note = NoteEvent(new_event_id("note"), values.track_id, values.pitch, values.onset_beats,
                         values.duration_beats, values.velocity, channel=0)
        result.notes.append(note)
    else:
        note = next(note for note in result.notes if note.id == note_id)
        note.pitch, note.onset_beats, note.duration_beats = values.pitch, values.onset_beats, values.duration_beats
        note.velocity, note.track_id = values.velocity, values.track_id
    note.role, note.transcription_status = values.role, values.transcription_status
    note.reference_evidence = None
    if result.reference is not None:
        start = reference_seconds(result.reference, note.onset_beats)
        end = reference_seconds(result.reference, note.offset_beats)
        if start is not None and end is not None:
            note.reference_evidence = NoteEvidence(result.reference.asset_id, start, end)
    result.notes.sort(key=lambda note: (note.onset_beats, note.track_id, note.pitch))
    return result


def align_score(doc: ScoreDocument, reference: ScoreReference) -> ScoreDocument:
    """Create a revision aligned to source audio without changing note pitches/times."""
    timing = create_draft(title="alignment", reference=reference)
    result = copy.deepcopy(doc)
    result.id = new_event_id("score")
    result.reference, result.tempos = reference, timing.tempos
    result.length_beats = max(doc.duration_beats, timing.length_beats)
    result.metadata.update({"parent_version": doc.id, "branch": "draft/aligned", "kind": "transcription"})
    for note in result.notes:
        start, end = reference_seconds(reference, note.onset_beats), reference_seconds(reference, note.offset_beats)
        note.reference_evidence = NoteEvidence(reference.asset_id, start, end) if start is not None and end is not None else None
        note.transcription_status = (note.transcription_status or "uncertain") if doc.reference == reference else "uncertain"
    return result
