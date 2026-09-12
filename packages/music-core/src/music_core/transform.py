"""Controlled score transforms (design doc issues #5 and #6, section 7.3).

Every transform returns a *new* :class:`~music_core.ir.ScoreDocument` on a new
version/branch; the source document is never mutated (design red line:
"所有变换生成新版本，不原地覆盖正式材料"). Note IDs are preserved across a
transform so that :mod:`music_core.diff` can describe the change as a move or
resize rather than a delete+add. Brand-new notes (none in MVP-0) would get
fresh IDs from :func:`~music_core.ir.new_event_id`.

Each transform also returns a deterministic :class:`ValidationReport`
(section 7.4) so the caller can prove the result stays playable before any
heuristic or rendering claim is made.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from music_core.ir import (
    NoteEvent,
    Region,
    ScoreDocument,
    new_event_id,
)
from music_core.validation import ValidationReport, validate_region


@dataclass(frozen=True)
class TransformRequest:
    """Generic transform request (design doc section 7.3).

    ``operation`` is one of ``"delay_bass_resolution"`` or
    ``"rhythmic_scaling"``; ``parameters`` carries the operation-specific
    knobs. ``preserve``/``vary`` are recorded for provenance only.
    """

    source_version_id: str
    region: Region
    operation: str
    parameters: dict[str, str | int | float | bool]
    preserve: list[str]
    vary: list[str]
    output_branch: str


@dataclass(frozen=True)
class TransformResult:
    """The output of a controlled transform."""

    document: ScoreDocument
    branch: str
    operation: str
    description: str
    changed_event_ids: list[str]
    validation: ValidationReport


def _clone_note(note: NoteEvent) -> NoteEvent:
    """Deep-ish copy of a note so the source document is never mutated."""
    return NoteEvent(
        id=note.id,
        track_id=note.track_id,
        pitch=note.pitch,
        onset_beats=note.onset_beats,
        duration_beats=note.duration_beats,
        velocity=note.velocity,
        voice_id=note.voice_id,
        channel=note.channel,
        articulations=list(note.articulations),
        source_ref=note.source_ref,
        role=note.role,
        transcription_status=note.transcription_status,
        reference_evidence=note.reference_evidence,
    )


def _fork_document(doc: ScoreDocument, *, branch: str) -> ScoreDocument:
    """Copy ``doc`` under a new version id (``branch``) for mutation."""
    return ScoreDocument(
        id=new_event_id("score"),
        ppq=doc.ppq,
        notes=[_clone_note(n) for n in doc.notes],
        tempos=list(doc.tempos),
        meters=list(doc.meters),
        markers=copy.deepcopy(doc.markers),
        metadata={**doc.metadata, "branch": branch, "parent_version": doc.id},
        channel_events=list(doc.channel_events),
        length_beats=doc.length_beats,
        reference=doc.reference,
    )


def _bass_note_ids(notes: list[NoteEvent]) -> set[str]:
    """IDs of notes that are the lowest pitch sounding at their own onset.

    This is a deterministic bass-voice detector: a note belongs to the bass
    line when no simultaneously-sounding note is lower. It avoids relying on
    track naming, which imported MIDI cannot guarantee.

    TODO: O(n^2) over the region's notes. Fine for hundreds of notes; revisit
    if regions grow large.
    """
    bass_ids: set[str] = set()
    for note in notes:
        if note.duration_beats <= 0.0:
            continue
        lowest = True
        for other in notes:
            if other is note or other.duration_beats <= 0.0:
                continue
            if (
                other.onset_beats <= note.onset_beats < other.offset_beats
                and other.pitch < note.pitch
            ):
                lowest = False
                break
        if lowest:
            bass_ids.add(note.id)
    return bass_ids


def delay_bass_resolution(
    doc: ScoreDocument,
    region: Region,
    *,
    delay_beats: float,
    branch: str = "exp/delayed-bass",
) -> TransformResult:
    """Delay the bass voice onset inside ``region`` by ``delay_beats``.

    This is the slice's core "controlled" transform: it changes exactly one
    variable — *when* the bass resolves — by shifting each bass note's onset
    later, without altering pitch, duration, or any other voice. Bass notes
    are detected as the lowest simultaneously-sounding note at each onset
    (see :func:`_bass_note_ids`), so the transform is robust to track naming.

    Shifts are clamped so a delayed bass note cannot cross the next bass
    onset in the same track or escape the region; clamped notes are reported
    in the validation warnings.
    """
    if not math.isfinite(delay_beats) or delay_beats < 0.0:
        raise ValueError(f"delay_beats must be non-negative, got {delay_beats}")
    forked = _fork_document(doc, branch=branch)
    region_notes = [n for n in forked.notes if region.start_beat <= n.onset_beats < region.end_beat]
    scope_ids = {n.id for n in doc.select_region(region)}
    in_scope = [n for n in region_notes if n.id in scope_ids]
    eligible = [n for n in doc.notes
                if (region.track_ids is None or n.track_id in region.track_ids)
                and (region.voice_ids is None or n.voice_id in region.voice_ids)]
    bass_ids = _bass_note_ids(eligible)

    changed: list[str] = []
    warnings: list[str] = []
    # Clamp each shift so the delayed onset stays strictly before the next
    # bass onset in the same track and inside the region (preserves order).
    _EPS = 1e-6
    for note in in_scope:
        if note.id not in bass_ids:
            continue
        next_onsets = [
            n.onset_beats
            for n in doc.notes
            if n.id in bass_ids
            and n.track_id == note.track_id
            and n.onset_beats > note.onset_beats
        ]
        ceiling = min([*next_onsets, region.end_beat])
        desired = note.onset_beats + delay_beats
        # ceiling > note.onset_beats always (in_scope onset < region end, and
        # every next onset is > this onset), so the clamp below keeps
        # new_onset strictly inside [onset, ceiling).
        new_onset = max(note.onset_beats, min(desired, ceiling - _EPS))
        if new_onset < desired:
            warnings.append(
                f"bass note {note.id}: delay clamped from {delay_beats} to "
                f"{new_onset - note.onset_beats:.3f} to stay before the next bass onset/region end"
            )
        if new_onset != note.onset_beats:
            note.onset_beats = new_onset
            changed.append(note.id)

    # TODO: validation only warns on same-pitch overlaps. Asymmetric clamping
    # can also create general bass-voice overlaps/gaps; consider a dedicated
    # bass-collision warning.
    validation = validate_region(forked, region=region)
    validation.warnings.extend(warnings)
    validation.warnings.append("This shifts low-note attacks; no harmonic resolution or cadence has been inferred.")
    if doc.channel_events:
        validation.warnings.append("Performance events (including pedal) retain their original timing; audition the result.")
    bars_note = f"{len(changed)} bass note(s)"
    return TransformResult(
        document=forked,
        branch=branch,
        operation="delay_bass_resolution",
        description=(
            f"Delayed bass resolution by up to {delay_beats} beats "
            f"({bars_note} moved)."
        ),
        changed_event_ids=sorted(changed),
        validation=validation,
    )


def rhythmic_scaling(
    doc: ScoreDocument,
    region: Region,
    *,
    factor: float,
    branch: str | None = None,
) -> TransformResult:
    """Rhythmic augmentation (``factor`` > 1) or diminution (``factor`` < 1).

    Notes whose onset falls inside ``region`` have their position and duration
    scaled relative to the region start. Material outside the region is left
    untouched — this is the "one variable" guarantee — so augmentation may
    cause the stretched notes to overlap later material; that is surfaced as a
    validation warning rather than silently "fixed".
    """
    # TODO: scaling moves notes in absolute beats but leaves the conductor map
    # (tempos/meters/markers) untouched, so a scaled region can desync from
    # bar/meter boundaries. Decide whether to also scale the map or warn.
    if not math.isfinite(factor) or factor <= 0.0:
        raise ValueError(f"factor must be positive, got {factor}")
    if factor == 1.0:
        raise ValueError("factor == 1.0 would leave the score unchanged")
    label = "augmentation" if factor > 1.0 else "diminution"
    resolved_branch = branch or f"exp/rhythmic-{label}"
    forked = _fork_document(doc, branch=resolved_branch)
    changed: list[str] = []
    for note in forked.notes:
        if region.track_ids is not None and note.track_id not in region.track_ids:
            continue
        if region.voice_ids is not None and note.voice_id not in region.voice_ids:
            continue
        if region.start_beat <= note.onset_beats < region.end_beat:
            note.onset_beats = region.start_beat + (note.onset_beats - region.start_beat) * factor
            note.duration_beats = note.duration_beats * factor
            changed.append(note.id)

    validation = validate_region(forked)
    if any(n.id in changed and n.offset_beats > region.end_beat for n in forked.notes):
        validation.warnings.append("Scaled notes extend past the selected region; later material and tempo/meter maps remain fixed.")
    if doc.channel_events:
        validation.warnings.append("Performance events (including pedal) retain their original timing; audition the result.")
    return TransformResult(
        document=forked,
        branch=resolved_branch,
        operation="rhythmic_scaling",
        description=(
            f"Rhythmic {label} by factor {factor} applied to {len(changed)} "
            f"note(s) in the region."
        ),
        changed_event_ids=sorted(changed),
        validation=validation,
    )


def shift_note_onset(
    doc: ScoreDocument, region: Region, *, note_id: str, shift_beats: float,
    branch: str = "exp/attack-shift",
) -> TransformResult:
    """Move one explicitly selected attack while retaining pitch and duration."""
    if not math.isfinite(shift_beats) or shift_beats == 0:
        raise ValueError("shift_beats must be finite and nonzero")
    note = next((n for n in doc.select_region(region) if n.id == note_id), None)
    if note is None or not region.start_beat <= note.onset_beats < region.end_beat:
        raise ValueError("choose a note whose attack lies inside the selected region")
    onset = note.onset_beats + shift_beats
    if not region.start_beat <= onset < region.end_beat:
        raise ValueError("shifted attack must remain inside the selected region")
    forked = _fork_document(doc, branch=branch)
    target = next(n for n in forked.notes if n.id == note_id)
    target.onset_beats = onset
    report = validate_region(forked)
    if target.offset_beats > region.end_beat:
        report.warnings.append("The moved note sustains past the region end because its duration is preserved.")
    if doc.channel_events:
        report.warnings.append("Pedal and other performance events keep their original timing.")
    return TransformResult(forked, branch, "shift_note_onset",
                           f"Moved note {note_id} by {shift_beats:g} beats; pitch, duration and velocity preserved.",
                           [note_id], report)


def _numeric_parameter(request: TransformRequest, key: str) -> float:
    value = request.parameters.get(key)
    if value is None or isinstance(value, bool):
        raise ValueError(f"{key} is required and must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{key} must be a finite number")
    return result


def apply_transform(doc: ScoreDocument, request: TransformRequest) -> TransformResult:
    """Dispatch a :class:`TransformRequest` to the named operation."""
    op = request.operation
    params = request.parameters
    if op == "delay_bass_resolution":
        delay = _numeric_parameter(request, "delay_beats")
        return delay_bass_resolution(
            doc, request.region, delay_beats=delay, branch=request.output_branch
        )
    if op == "rhythmic_scaling":
        factor = _numeric_parameter(request, "factor")
        return rhythmic_scaling(
            doc, request.region, factor=factor, branch=request.output_branch
        )
    if op == "shift_note_onset":
        note_id = params.get("note_id")
        if not isinstance(note_id, str):
            raise ValueError("note_id is required for shifting one attack")
        return shift_note_onset(doc, request.region, note_id=note_id,
                                shift_beats=_numeric_parameter(request, "shift_beats"),
                                branch=request.output_branch)
    raise ValueError(f"Unknown transform operation: {op!r}")
