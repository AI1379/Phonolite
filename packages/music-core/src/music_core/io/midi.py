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

CC (including sustain), program changes, pitch bend and pressure are retained
in the IR and re-emitted. Unsupported meta/system data emits import warnings.
SMPTE and asynchronous type-2 files are rejected.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from collections.abc import Sequence
from dataclasses import replace

import mido

from music_core.ir import (
    MetadataValue,
    MidiChannelEvent,
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
    try:
        midi = mido.MidiFile(file=BytesIO(data))
    except (EOFError, OSError) as exc:
        raise ValueError("Invalid or truncated Standard MIDI File") from exc
    return _convert(midi, document_id=document_id)


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
    if mid.type == 2:
        raise ValueError("Asynchronous type-2 MIDI tracks cannot share a score timeline")
    ppq = mid.ticks_per_beat

    # Collected per physical file track; IR track IDs are assigned only to
    # note-bearing tracks after the scan (see module docstring).
    collected: list[tuple[int, NoteEvent]] = []  # (physical track index, note)
    tempos: list[TempoEvent] = []
    meters: list[MeterEvent] = []
    warnings: list[str] = []
    note_bearing: list[int] = []  # physical indices, in order
    names_by_physical: dict[int, str] = {}
    performance: list[tuple[int, MidiChannelEvent]] = []
    ignored: dict[str, int] = {}
    end_beats = 0.0

    for physical_index, track in enumerate(mid.tracks):
        abs_tick = 0
        last_tick = 0
        has_channel_events = False
        # Open note_on events awaiting their note_off, FIFO per pitch.
        pending: dict[tuple[int, int], list[tuple[int, int]]] = {}

        for order, msg in enumerate(track):
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
                elif msg.type not in ("track_name", "end_of_track"):
                    ignored[msg.type] = ignored.get(msg.type, 0) + 1
                continue

            if msg.type == "sysex":
                ignored[msg.type] = ignored.get(msg.type, 0) + 1
                continue
            has_channel_events = True
            event = _performance_event(msg, abs_tick / ppq, order)
            if event is not None:
                performance.append((physical_index, event))
                continue
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
            else:
                ignored[msg.type] = ignored.get(msg.type, 0) + 1

        end_beats = max(end_beats, last_tick / ppq)
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
    warnings.extend(f"Unsupported MIDI {kind}: {count} event(s) not retained"
                    for kind, count in sorted(ignored.items()))
    metadata["import_warnings"] = list(warnings)
    return ScoreDocument(
        id=document_id or new_event_id("score"),
        ppq=ppq,
        notes=sorted(notes, key=lambda n: (n.track_id, n.onset_beats, n.pitch)),
        tempos=sorted(tempos, key=lambda t: t.beat),
        meters=sorted(meters, key=lambda m: m.beat),
        metadata=metadata,
        channel_events=[replace(event, track_id=track_ids[physical])
                        for physical, event in performance],
        length_beats=end_beats,
    )


def _performance_event(msg: mido.Message, beat: float, order: int) -> MidiChannelEvent | None:
    """Narrow dynamic mido channel data at the IO boundary."""
    kind: object = getattr(msg, "type", None)
    if kind not in ("control_change", "program_change", "pitchwheel", "aftertouch", "polytouch"):
        return None
    channel = _message_int(msg, "channel")
    if kind == "control_change":
        return MidiChannelEvent("", beat, channel, "control_change", (_message_int(msg, "control"), _message_int(msg, "value")), order)
    if kind == "program_change":
        return MidiChannelEvent("", beat, channel, "program_change", (_message_int(msg, "program"),), order)
    if kind == "pitchwheel":
        return MidiChannelEvent("", beat, channel, "pitchwheel", (_message_int(msg, "pitch"),), order)
    if kind == "aftertouch":
        return MidiChannelEvent("", beat, channel, "aftertouch", (_message_int(msg, "value"),), order)
    if kind == "polytouch":
        return MidiChannelEvent("", beat, channel, "polytouch", (_message_int(msg, "note"), _message_int(msg, "value")), order)
    return None


def _message_int(msg: mido.Message, field: str) -> int:
    value: object = getattr(msg, field, None)
    if not isinstance(value, int):
        raise ValueError(f"MIDI {field} must be an integer")
    return value


def _performance_message(event: MidiChannelEvent) -> mido.Message:
    values = event.values
    if event.kind == "control_change":
        return mido.Message(event.kind, channel=event.channel, control=values[0], value=values[1])
    elif event.kind == "program_change":
        return mido.Message(event.kind, channel=event.channel, program=values[0])
    elif event.kind == "pitchwheel":
        return mido.Message(event.kind, channel=event.channel, pitch=values[0])
    elif event.kind == "polytouch":
        return mido.Message(event.kind, channel=event.channel, note=values[0], value=values[1])
    return mido.Message(event.kind, channel=event.channel, value=values[0])


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
    for event in doc.channel_events:
        notes_by_track.setdefault(event.track_id, [])

    for track_id in sorted(notes_by_track, key=lambda name: (
        int(name[6:]) if name.startswith("track-") and name[6:].isdigit() else -1, name
    )):
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
        # Retain controller ordering at equal beats. Controllers precede notes
        # on export so program/pedal state is ready for a simultaneous attack.
        controls = [(round(event.beat * doc.ppq), _performance_message(event))
                    for event in sorted(doc.channel_events, key=lambda event: (event.beat, event.order))
                    if event.track_id == track_id]
        events = sorted([*controls, *events], key=lambda item: item[0])

        head: list[tuple[int, mido.MetaMessage]] = []
        if track_id in track_names:
            head.append(
                (0, mido.MetaMessage("track_name", name=track_names[track_id], time=0))
            )
        mid.tracks.append(_deltas([*head, *events]))

    end_tick = max([round(doc.duration_beats * doc.ppq),
                    *(sum(int(getattr(message, "time", 0)) for message in track) for track in mid.tracks)])
    for track in mid.tracks:
        elapsed = sum(int(getattr(message, "time", 0)) for message in track)
        track.append(mido.MetaMessage("end_of_track", time=max(0, end_tick - elapsed)))

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
