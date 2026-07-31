"""Standard MIDI file import/export for the Score IR.

Implements design doc issue #2 (``io: MIDI import/export round-trip``).

Conventions:
  - Both SMF type 0 and type 1 files import; export always writes type 1
    with a dedicated conductor track (tempo/meter map) at position 0.
  - Ticks convert to beats via the file's PPQ; SMPTE timecode is rejected.
  - Track IDs are positional among *note-bearing* tracks (``track-0`` …);
    a meta-only conductor track is not numbered. This keeps track IDs
    stable across round-trips even though export inserts the conductor
    track at file position 0.
  - Note pairing is per ``(channel, pitch)`` FIFO, so overlapping repeated
    notes on one channel stay intact. ``note_on`` with velocity 0 is
    treated as ``note_off``.
  - Data the IR cannot represent is never dropped silently: problems are
    collected as human-readable strings in ``metadata["import_warnings"]``
    (unmatched ``note_off``, unclosed ``note_on`` at end of track).
  - ``track_name`` meta events on note-bearing tracks are preserved via
    ``metadata["track_names"]`` and re-emitted on export.

Out of scope (MVP): program changes, CC, pitch bend, aftertouch, markers,
lyrics, SMPTE. These are ignored on import.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from collections.abc import Sequence

import mido

from music_core.ir import (
    MetadataValue,
    MeterEvent,
    NoteEvent,
    ScoreDocument,
    TempoEvent,
    new_event_id,
)


def load_midi(path: str | Path, *, document_id: str | None = None) -> ScoreDocument:
    """Load a standard MIDI file from ``path`` into a ScoreDocument."""
    return _convert(mido.MidiFile(str(path)), document_id=document_id)


def loads_midi(data: bytes, *, document_id: str | None = None) -> ScoreDocument:
    """Load a standard MIDI file from a bytes buffer into a ScoreDocument."""
    return _convert(mido.MidiFile(file=BytesIO(data)), document_id=document_id)


def dump_midi(doc: ScoreDocument, path: str | Path) -> None:
    """Write ``doc`` to ``path`` as an SMF type 1 file."""
    _to_midi_file(doc).save(str(path))


def dumps_midi(doc: ScoreDocument) -> bytes:
    """Serialize ``doc`` to SMF type 1 bytes."""
    buffer = BytesIO()
    _to_midi_file(doc).save(file=buffer)
    return buffer.getvalue()


def _convert(mid: mido.MidiFile, *, document_id: str | None) -> ScoreDocument:
    """Shared import logic for an opened :class:`mido.MidiFile`."""
    if mid.ticks_per_beat is None or mid.ticks_per_beat <= 0:
        raise ValueError("SMPTE-timecode MIDI files are not supported")
    ppq = mid.ticks_per_beat

    # Collected per physical file track; IR track IDs are assigned only to
    # note-bearing tracks after the scan (see module docstring).
    collected: list[tuple[int, NoteEvent]] = []  # (physical track index, note)
    tempos: list[TempoEvent] = []
    meters: list[MeterEvent] = []
    warnings: list[str] = []
    note_bearing: list[int] = []  # physical indices, in order
    names_by_physical: dict[int, str] = {}

    for physical_index, track in enumerate(mid.tracks):
        abs_tick = 0
        last_tick = 0
        has_channel_events = False
        # Open note_on events awaiting their note_off, FIFO per pitch.
        pending: dict[tuple[int, int], list[tuple[int, int]]] = {}

        for msg in track:
            abs_tick += msg.time
            last_tick = abs_tick

            if msg.is_meta:
                if msg.type == "set_tempo":
                    tempos.append(
                        TempoEvent(beat=abs_tick / ppq, bpm=mido.tempo2bpm(msg.tempo))
                    )
                elif msg.type == "time_signature":
                    meters.append(
                        MeterEvent(
                            beat=abs_tick / ppq,
                            numerator=msg.numerator,
                            denominator=msg.denominator,
                        )
                    )
                elif msg.type == "track_name" and physical_index not in names_by_physical:
                    names_by_physical[physical_index] = msg.name
                continue

            has_channel_events = True
            is_note_on = msg.type == "note_on" and msg.velocity > 0
            is_note_off = msg.type == "note_off" or (
                msg.type == "note_on" and msg.velocity == 0
            )
            if is_note_on:
                pending.setdefault((msg.channel, msg.note), []).append(
                    (abs_tick, msg.velocity)
                )
            elif is_note_off:
                starts = pending.get((msg.channel, msg.note))
                if starts:
                    start_tick, velocity = starts.pop(0)
                    if not starts:
                        del pending[(msg.channel, msg.note)]
                    collected.append(
                        (
                            physical_index,
                            _make_note(
                                physical_index=physical_index,
                                pitch=msg.note,
                                start_tick=start_tick,
                                end_tick=abs_tick,
                                velocity=velocity,
                                channel=msg.channel,
                                ppq=ppq,
                            ),
                        )
                    )
                else:
                    warnings.append(
                        f"unmatched note_off {msg.note} in file track "
                        f"{physical_index} at tick {abs_tick}"
                    )

        if has_channel_events:
            note_bearing.append(physical_index)

        # Notes still open when the track ends: close them at the last
        # event tick rather than dropping the user's material.
        for (channel, pitch), starts in pending.items():
            for start_tick, velocity in starts:
                warnings.append(
                    f"unclosed note_on {pitch} in file track {physical_index} "
                    f"at tick {start_tick}; closed at track end ({last_tick})"
                )
                collected.append(
                    (
                        physical_index,
                        _make_note(
                            physical_index=physical_index,
                            pitch=pitch,
                            start_tick=start_tick,
                            end_tick=last_tick,
                            velocity=velocity,
                            channel=channel,
                            ppq=ppq,
                        ),
                    )
                )

    # Assign stable IR track IDs to note-bearing tracks, in file order.
    track_ids = {physical: f"track-{n}" for n, physical in enumerate(note_bearing)}
    notes = [note for _, note in collected]
    for (physical, note) in collected:
        note.track_id = track_ids[physical]
    track_names = {
        track_ids[physical]: name
        for physical, name in names_by_physical.items()
        if physical in track_ids
    }

    metadata: dict[str, MetadataValue] = {
        "midi_format": mid.type,
        "track_names": dict(track_names),
        "import_warnings": list(warnings),
    }
    return ScoreDocument(
        id=document_id or new_event_id("score"),
        ppq=ppq,
        notes=sorted(notes, key=lambda n: (n.track_id, n.onset_beats, n.pitch)),
        tempos=sorted(tempos, key=lambda t: t.beat),
        meters=sorted(meters, key=lambda m: m.beat),
        metadata=metadata,
    )


def _make_note(
    *,
    physical_index: int,
    pitch: int,
    start_tick: int,
    end_tick: int,
    velocity: int,
    channel: int,
    ppq: int,
) -> NoteEvent:
    return NoteEvent(
        id=new_event_id("note"),
        # Placeholder; reassigned once note-bearing tracks are numbered.
        track_id=f"file-track-{physical_index}",
        pitch=pitch,
        onset_beats=start_tick / ppq,
        duration_beats=(end_tick - start_tick) / ppq,
        velocity=velocity,
        channel=channel,
        source_ref=f"midi:file-track{physical_index}@{start_tick}",
    )


def _to_midi_file(doc: ScoreDocument) -> mido.MidiFile:
    """Build a type 1 :class:`mido.MidiFile` from a ScoreDocument."""
    mid = mido.MidiFile(type=1, ticks_per_beat=doc.ppq)

    # Conductor track: tempo map + meter map (SMF type 1 convention).
    meta_events: list[tuple[int, mido.MetaMessage]] = []
    for tempo in doc.tempos:
        meta_events.append(
            (
                round(tempo.beat * doc.ppq),
                mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo.bpm), time=0),
            )
        )
    for meter in doc.meters:
        meta_events.append(
            (
                round(meter.beat * doc.ppq),
                mido.MetaMessage(
                    "time_signature",
                    numerator=meter.numerator,
                    denominator=meter.denominator,
                    time=0,
                ),
            )
        )
    mid.tracks.append(_deltas(sorted(meta_events, key=lambda e: e[0])))

    # One MIDI track per IR track, sorted for deterministic output.
    raw_track_names = doc.metadata.get("track_names", {})
    track_names = (
        {key: value for key, value in raw_track_names.items() if isinstance(value, str)}
        if isinstance(raw_track_names, dict)
        else {}
    )
    notes_by_track: dict[str, list[NoteEvent]] = {}
    for note in doc.notes:
        notes_by_track.setdefault(note.track_id, []).append(note)

    for track_id in sorted(notes_by_track):
        events: list[tuple[int, mido.Message]] = []
        for note in notes_by_track[track_id]:
            channel = note.channel if note.channel is not None else 0
            events.append(
                (
                    round(note.onset_beats * doc.ppq),
                    mido.Message(
                        "note_on",
                        channel=channel,
                        note=note.pitch,
                        velocity=note.velocity,
                        time=0,
                    ),
                )
            )
            events.append(
                (
                    round(note.offset_beats * doc.ppq),
                    mido.Message(
                        "note_off",
                        channel=channel,
                        note=note.pitch,
                        velocity=64,
                        time=0,
                    ),
                )
            )
        # note_off before note_on at the same tick, so a re-articulated
        # note is not cut short by its own release.
        events.sort(
            key=lambda event: (
                event[0],
                0 if getattr(event[1], "type", "") == "note_off" else 1,
                int(getattr(event[1], "note", -1)),
            )
        )

        head: list[tuple[int, mido.MetaMessage]] = []
        if track_id in track_names:
            head.append(
                (0, mido.MetaMessage("track_name", name=track_names[track_id], time=0))
            )
        mid.tracks.append(_deltas([*head, *events]))

    for track in mid.tracks:
        track.append(mido.MetaMessage("end_of_track", time=0))

    return mid


def _deltas(
    events: Sequence[tuple[int, mido.Message | mido.MetaMessage]],
) -> mido.MidiTrack:
    """Convert ``(abs_tick, message)`` pairs into a delta-timed MidiTrack."""
    track = mido.MidiTrack()
    previous_tick = 0
    for abs_tick, msg in events:
        msg.time = abs_tick - previous_tick
        previous_tick = abs_tick
        track.append(msg)
    return track
