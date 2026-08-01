"""Semantic score diff keyed on stable event IDs (design doc issue #7).

Because transforms preserve note IDs (see :mod:`music_core.transform`) and
IDs are minted once and never recycled (see :mod:`music_core.ir`), a diff can
describe *how* each note changed — moved, resized, retuned — instead of just
listing adds/removes. That semantic mapping is what the A/B selection step of
the vertical slice needs to show the user "what actually differs".

Comparisons use a small tolerance for beat values so that MIDI round-trip
quantisation noise does not register as a change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from music_core.ir import NoteEvent, ScoreDocument

# Beat tolerance: anything smaller than this is treated as unchanged, so
# float drift from MIDI tick quantisation does not produce noise.
_BEAT_EPS = 1e-6

FieldValue = str | int | float | None


@dataclass(frozen=True)
class NoteChange:
    """How a single note changed between two versions."""

    note_id: str
    kind: str  # "added" | "removed" | "moved" | "resized" | "moved_resized" | "changed"
    before: NoteEvent | None
    after: NoteEvent | None
    field_changes: dict[str, tuple[FieldValue, FieldValue]] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoreDiff:
    """Full diff between two score versions."""

    added: list[NoteChange]
    removed: list[NoteChange]
    modified: list[NoteChange]
    unchanged_count: int

    @property
    def is_empty(self) -> bool:
        """True when the two versions are semantically identical."""
        return not self.added and not self.removed and not self.modified

    @property
    def summary(self) -> str:
        """One-line human-readable summary of the change counts."""
        parts = [f"{len(self.added)} added", f"{len(self.removed)} removed"]
        if self.modified:
            by_kind: dict[str, int] = {}
            for c in self.modified:
                by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
            parts.append(
                ", ".join(f"{count} {kind}" for kind, count in sorted(by_kind.items()))
            )
        parts.append(f"{self.unchanged_count} unchanged")
        return "; ".join(parts) + "."


def _approx_equal(a: float, b: float) -> bool:
    return abs(a - b) <= _BEAT_EPS


def _classify_and_diff(before: NoteEvent, after: NoteEvent) -> NoteChange:
    """Produce the NoteChange for two notes that share an ID."""
    changes: dict[str, tuple[FieldValue, FieldValue]] = {}
    onset_changed = False
    duration_changed = False

    if before.pitch != after.pitch:
        changes["pitch"] = (before.pitch, after.pitch)
    if not _approx_equal(before.onset_beats, after.onset_beats):
        changes["onset_beats"] = (before.onset_beats, after.onset_beats)
        onset_changed = True
    if not _approx_equal(before.duration_beats, after.duration_beats):
        changes["duration_beats"] = (before.duration_beats, after.duration_beats)
        duration_changed = True
    if before.velocity != after.velocity:
        changes["velocity"] = (before.velocity, after.velocity)
    if before.track_id != after.track_id:
        changes["track_id"] = (before.track_id, after.track_id)
    if before.voice_id != after.voice_id:
        changes["voice_id"] = (before.voice_id, after.voice_id)
    if before.channel != after.channel:
        changes["channel"] = (before.channel, after.channel)

    # TODO: `kind` classifies by geometry (onset/duration), so a simultaneous
    # pitch change is only visible in `field_changes`, not in the summary kind.
    # Consider letting a pitch change take precedence in `kind` for clarity.
    if onset_changed and duration_changed:
        kind = "moved_resized"
    elif onset_changed:
        kind = "moved"
    elif duration_changed:
        kind = "resized"
    else:
        kind = "changed"
    return NoteChange(
        note_id=before.id, kind=kind, before=before, after=after, field_changes=changes
    )


def diff(before: ScoreDocument, after: ScoreDocument) -> ScoreDiff:
    """Compare two score versions by stable note ID."""
    before_by_id = {n.id: n for n in before.notes}
    after_by_id = {n.id: n for n in after.notes}

    added: list[NoteChange] = []
    removed: list[NoteChange] = []
    modified: list[NoteChange] = []
    unchanged = 0

    for note_id, after_note in after_by_id.items():
        before_note = before_by_id.get(note_id)
        if before_note is None:
            added.append(
                NoteChange(note_id, "added", None, after_note, {})
            )
        else:
            change = _classify_and_diff(before_note, after_note)
            if change.field_changes:
                modified.append(change)
            else:
                unchanged += 1

    for note_id, before_note in before_by_id.items():
        if note_id not in after_by_id:
            removed.append(
                NoteChange(note_id, "removed", before_note, None, {})
            )

    return ScoreDiff(
        added=sorted(added, key=lambda c: c.note_id),
        removed=sorted(removed, key=lambda c: c.note_id),
        modified=sorted(modified, key=lambda c: c.note_id),
        unchanged_count=unchanged,
    )
