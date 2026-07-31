"""Round-trip and edge-case tests for MIDI IO (design doc issue #2)."""

from __future__ import annotations

from io import BytesIO
from typing import cast

import mido
import pytest

from music_core.ir import MeterEvent, NoteEvent, ScoreDocument, TempoEvent
from music_core.io.midi import dumps_midi, loads_midi


def make_doc() -> ScoreDocument:
    """Two tracks, overlapping repeated notes, tempo + meter maps, names."""
    return ScoreDocument(
        id="v001",
        ppq=480,
        notes=[
            NoteEvent(
                id="n1", track_id="track-0", pitch=60,
                onset_beats=0.0, duration_beats=1.0, velocity=80, channel=0,
            ),
            # Overlapping same pitch on the same channel: FIFO pairing must
            # keep both notes intact.
            NoteEvent(
                id="n2", track_id="track-0", pitch=60,
                onset_beats=0.5, duration_beats=1.0, velocity=70, channel=0,
            ),
            NoteEvent(
                id="n3", track_id="track-0", pitch=64,
                onset_beats=2.0, duration_beats=0.5, velocity=90, channel=0,
            ),
            NoteEvent(
                id="n4", track_id="track-1", pitch=36,
                onset_beats=0.0, duration_beats=2.0, velocity=100, channel=1,
            ),
        ],
        tempos=[TempoEvent(beat=0.0, bpm=72.0), TempoEvent(beat=8.0, bpm=96.0)],
        meters=[MeterEvent(beat=0.0, numerator=9, denominator=8)],
        metadata={"track_names": {"track-0": "piano", "track-1": "bass"}},
    )


def assert_notes_equal(a: ScoreDocument, b: ScoreDocument) -> None:
    def key(n: NoteEvent) -> tuple[str, float, int, int]:
        return (n.track_id, n.onset_beats, n.pitch, n.velocity)

    na, nb = sorted(a.notes, key=key), sorted(b.notes, key=key)
    assert len(na) == len(nb)
    for x, y in zip(na, nb):
        assert x.track_id == y.track_id
        assert x.pitch == y.pitch
        assert x.onset_beats == pytest.approx(y.onset_beats)
        assert x.duration_beats == pytest.approx(y.duration_beats)
        assert x.velocity == y.velocity
        assert x.channel == y.channel


def assert_tempos_equal(a: ScoreDocument, b: ScoreDocument) -> None:
    assert len(a.tempos) == len(b.tempos)
    for x, y in zip(a.tempos, b.tempos):
        assert x.beat == pytest.approx(y.beat)
        assert x.bpm == pytest.approx(y.bpm)


def test_round_trip_preserves_notes_tempos_meters_and_names() -> None:
    doc = make_doc()
    back = loads_midi(dumps_midi(doc))

    assert back.ppq == doc.ppq
    assert_notes_equal(back, doc)
    assert_tempos_equal(back, doc)
    assert back.meters == doc.meters
    assert back.metadata["track_names"] == doc.metadata["track_names"]
    assert back.metadata["import_warnings"] == []


def test_export_is_byte_deterministic_across_reimport() -> None:
    once = dumps_midi(make_doc())
    twice = dumps_midi(loads_midi(once))
    assert once == twice


def test_track_ids_stable_when_conductor_track_present() -> None:
    # Foreign type 1 file: dedicated meta-only track 0, notes in track 1+.
    mid = mido.MidiFile(type=1, ticks_per_beat=480)
    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120.0), time=0))
    conductor.append(mido.MetaMessage("end_of_track", time=0))
    notes_track = mido.MidiTrack()
    notes_track.append(mido.Message("note_on", channel=0, note=64, velocity=80, time=0))
    notes_track.append(mido.Message("note_off", channel=0, note=64, velocity=64, time=480))
    notes_track.append(mido.MetaMessage("end_of_track", time=0))
    mid.tracks.extend([conductor, notes_track])

    buffer = BytesIO()
    mid.save(file=buffer)
    doc = loads_midi(buffer.getvalue())

    assert {n.track_id for n in doc.notes} == {"track-0"}
    # And its own export/import cycle keeps the same IDs.
    back = loads_midi(dumps_midi(doc))
    assert {n.track_id for n in back.notes} == {"track-0"}


def test_import_handles_malformed_note_streams() -> None:
    mid = mido.MidiFile(type=1, ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    # Closed by note_on velocity 0.
    track.append(mido.Message("note_on", channel=0, note=60, velocity=80, time=0))
    track.append(mido.Message("note_on", channel=0, note=60, velocity=0, time=240))
    # Stray note_off: nothing pending.
    track.append(mido.Message("note_off", channel=0, note=72, velocity=64, time=0))
    # Never closed: ends up closed at track end (tick 720).
    track.append(mido.Message("note_on", channel=0, note=65, velocity=90, time=120))
    track.append(mido.MetaMessage("end_of_track", time=360))

    buffer = BytesIO()
    mid.save(file=buffer)
    doc = loads_midi(buffer.getvalue())

    by_pitch = {n.pitch: n for n in doc.notes}
    assert len(doc.notes) == 2
    assert by_pitch[60].duration_beats == pytest.approx(0.5)
    assert by_pitch[65].onset_beats == pytest.approx(0.75)
    assert by_pitch[65].duration_beats == pytest.approx(0.75)

    warnings = cast(list[str], doc.metadata["import_warnings"])
    assert len(warnings) == 2
    assert any("unmatched note_off 72" in w for w in warnings)
    assert any("unclosed note_on 65" in w for w in warnings)


def test_empty_document_round_trip() -> None:
    back = loads_midi(dumps_midi(ScoreDocument(id="empty", ppq=960)))
    assert back.ppq == 960
    assert back.notes == []
    assert back.metadata["import_warnings"] == []
