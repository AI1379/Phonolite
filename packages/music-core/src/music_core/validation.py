"""Deterministic score validation (design doc section 7.4).

Validators here are *deterministic* and run before any heuristic or LLM
claim about a score. They never declare music "wrong"; they only surface
objective problems (notes out of range, negative onsets, overlapping voices
in the same channel, etc.) as structured warnings/errors. Per the design
red lines, a validator may produce a warning but must not auto-judge the
music.

A :class:`ValidationReport` is part of every transform output, so the
caller can prove a transformation stayed within playable bounds.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from music_core.ir import NoteEvent, ScoreDocument, Region

# Practical MIDI bounds. The IR stores pitch as a MIDI note number, so
# anything outside [0, 127] is objectively unrepresentable.
_MIN_PITCH = 0
_MAX_PITCH = 127
# Conservative single-hand span for keyboard writing (a ninth). Exceeding it
# is a *warning*, not an error: the music may be valid for two hands or
# non-keyboard instruments.
_KEYBOARD_HAND_SPAN = 14


@dataclass(frozen=True)
class ValidationReport:
    """Aggregate result of validating a document or region.

    ``errors`` are objective failures (unrepresentable data); ``warnings`` are
    playability/style concerns the user may legitimately ignore. ``ok`` is
    True only when there are no errors.
    """

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when no objective errors were found."""
        return not self.errors

    def extend(self, other: ValidationReport) -> None:
        """Merge another report into this one (mutates in place)."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


def validate_note(note: NoteEvent) -> ValidationReport:
    """Objective checks for a single note's internal consistency."""
    errors: list[str] = []
    warnings: list[str] = []
    if note.onset_beats < 0.0:
        errors.append(f"note {note.id}: negative onset {note.onset_beats}")
    if note.duration_beats < 0.0:
        errors.append(f"note {note.id}: negative duration {note.duration_beats}")
    if not _MIN_PITCH <= note.pitch <= _MAX_PITCH:
        errors.append(f"note {note.id}: pitch {note.pitch} out of MIDI range")
    if not 0 <= note.velocity <= 127:
        errors.append(f"note {note.id}: velocity {note.velocity} out of range")
    if note.duration_beats == 0.0:
        warnings.append(f"note {note.id}: zero-length note at beat {note.onset_beats}")
    return ValidationReport(errors, warnings)


def _overlaps(a: NoteEvent, b: NoteEvent) -> bool:
    """True when two notes on the same channel sound at the same time."""
    return (
        a.onset_beats < (b.offset_beats if b.duration_beats > 0.0 else b.onset_beats)
        and b.onset_beats < (a.offset_beats if a.duration_beats > 0.0 else a.onset_beats)
    )


def validate_region(
    doc: ScoreDocument, region: Region | None = None
) -> ValidationReport:
    """Validate ``doc`` (or just the notes in ``region``).

    Checks: per-note bounds (see :func:`validate_note`), same-channel
    same-pitch overlap (a likely encoding bug rather than music), and a
    keyboard hand-span warning when simultaneous notes span more than a ninth.
    """
    notes = doc.select_region(region) if region is not None else list(doc.notes)
    report = ValidationReport()
    for note in notes:
        report.extend(validate_note(note))

    # Same-channel, same-pitch overlaps are almost always double-strike bugs.
    by_channel: dict[int | None, list[NoteEvent]] = {}
    for note in notes:
        by_channel.setdefault(note.channel, []).append(note)
    for channel, group in by_channel.items():
        group.sort(key=lambda n: (n.pitch, n.onset_beats))
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if b.pitch != a.pitch:
                    break
                if _overlaps(a, b):
                    report.warnings.append(
                        f"channel {channel}: overlapping same-pitch notes "
                        f"{a.id} and {b.id} at beat {a.onset_beats}"
                    )

    # Keyboard hand-span: within each simultaneous cluster, flag wide spans.
    by_part: dict[tuple[str, str | None], list[NoteEvent]] = {}
    for note in notes:
        by_part.setdefault((note.track_id, note.voice_id), []).append(note)
    for part in by_part.values():
        _flag_wide_spans(part, report)
    return report


def _flag_wide_spans(notes: list[NoteEvent], report: ValidationReport) -> None:
    """Warn when simultaneously-sounding notes exceed a keyboard hand span."""
    # Build clusters of overlapping notes via a sweep over onset/offset events.
    events: list[tuple[float, int, NoteEvent]] = []
    for note in notes:
        end = note.offset_beats if note.duration_beats > 0.0 else note.onset_beats
        if end <= note.onset_beats:
            continue
        events.append((note.onset_beats, 1, note))
        events.append((end, 0, note))
    events.sort(key=lambda e: (e[0], e[1]))
    active: set[int] = set()
    active_notes: dict[int, NoteEvent] = {}
    for _, kind, note in events:
        nid = id(note)
        if kind == 1:
            active.add(nid)
            active_notes[nid] = note
            if len(active) >= 2:
                pitches = [active_notes[k].pitch for k in active]
                span = max(pitches) - min(pitches)
                if span > _KEYBOARD_HAND_SPAN:
                    report.warnings.append(
                        f"simultaneous span {span} semitones (> {_KEYBOARD_HAND_SPAN}) "
                        f"near beat {note.onset_beats}; may exceed one hand"
                    )
        else:
            active.discard(nid)
            active_notes.pop(nid, None)


def validate_document(doc: ScoreDocument) -> ValidationReport:
    """Validate the whole document (convenience wrapper)."""
    return validate_region(doc, region=None)
