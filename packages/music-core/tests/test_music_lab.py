"""Musical boundary cases and actual audio checks for the browser workflow."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import wave

import mido
import numpy as np
import pytest

from music_core.analysis import analyze_density, analyze_harmony, analyze_register, analyze_rhythm
from music_core.io.midi import dumps_midi, loads_midi
from music_core.ir import MeterEvent, MidiChannelEvent, NoteEvent, Region, ScoreDocument, TempoEvent
from music_core.preview import sounding_end
from music_core.render import render_score
from music_core.timing import beat_to_seconds, region_bars
from music_core.transform import TransformRequest, apply_transform, shift_note_onset
from music_core.validation import validate_document


def _note(nid: str, pitch: int, onset: float, duration: float = 1.0) -> NoteEvent:
    return NoteEvent(nid, "track-0", pitch, onset, duration, 90, channel=0)


def _score(notes: list[NoteEvent]) -> ScoreDocument:
    return ScoreDocument("source", 480, notes, meters=[MeterEvent(0, 4, 4)])


def test_density_clips_sustained_notes_and_counts_only_attacks() -> None:
    doc = _score([_note("long", 60, 0, 8)])
    evidence = {item.metric: item.value for item in analyze_density(doc, Region(2, 3))[0].evidence}
    assert evidence["average_simultaneous_notes"] == 1
    assert evidence["notes_per_beat"] == 0
    assert evidence["note_count"] == 1


def test_bar_locations_cover_partial_end_and_meter_changes() -> None:
    doc = _score([_note("long", 60, 0, 12)])
    assert analyze_register(doc, Region(0, 6))[0].location.bars == (1, 2)
    doc.meters.append(MeterEvent(8, 3, 4))
    assert [(bar.number, bar.start, bar.end) for bar in region_bars(doc, Region(6, 12))] == [
        (2, 6, 8), (3, 8, 11), (4, 11, 12)
    ]
    assert analyze_register(doc, Region(8, 12))[0].location.bars == (3, 4)


def test_zero_length_and_empty_regions_are_consistent() -> None:
    doc = _score([_note("zero", 60, 0, 0)])
    assert len(doc.select_region(Region(0, 1))) == 1
    assert doc.select_region(Region(0, 0)) == []


def test_rhythm_compares_attacks_not_chord_size_and_skips_partial_bars() -> None:
    doc = _score([_note("a", 60, 0), _note("b", 64, 0), _note("c", 62, 2),
                  _note("d", 67, 4), _note("e", 65, 6, 2)])
    result = analyze_rhythm(doc)
    assert len(result) == 1
    assert result[0].evidence[0].value == 1.0
    assert set(result[0].note_ids) == {"a", "b", "c", "d", "e"}
    assert analyze_rhythm(doc, Region(1, 8)) == []
    doc.notes[-1].onset_beats = 7
    assert analyze_rhythm(doc) == []


def test_harmony_is_localized_and_does_not_invent_missing_tones() -> None:
    doc = _score([_note(str(p), p, 0, 4) for p in (60, 64, 67)] +
                 [_note(str(p), p, 4, 4) for p in (57, 60, 64)])
    findings = analyze_harmony(doc)
    assert len(findings) == 2
    assert findings[0].evidence[1].value == "C major"
    assert findings[1].evidence[1].value == "A minor"
    assert findings[1].location.bars == (2, 2)
    assert all(f.confidence < 1 and f.alternatives for f in findings)
    assert analyze_harmony(_score([_note("a", 60, 0), _note("b", 64, 0)])) == []


def test_midi_retains_performance_and_controller_only_track() -> None:
    mid = mido.MidiFile(ticks_per_beat=480)
    mid.tracks.append(mido.MidiTrack([
        mido.Message("program_change", channel=0, program=5),
        mido.Message("control_change", channel=0, control=64, value=127),
        mido.Message("pitchwheel", channel=0, pitch=100),
        mido.Message("aftertouch", channel=0, value=30),
        mido.Message("polytouch", channel=0, note=60, value=40),
        mido.Message("control_change", channel=0, control=64, value=0, time=960),
    ]))
    mid.tracks.append(mido.MidiTrack([
        mido.Message("note_on", note=60, velocity=90),
        mido.Message("note_off", note=60, time=480),
    ]))
    stream = BytesIO()
    mid.save(file=stream)
    doc = loads_midi(stream.getvalue())
    back = loads_midi(dumps_midi(doc))
    assert [(e.track_id, e.beat, e.channel, e.kind, e.values) for e in back.channel_events] == [
        (e.track_id, e.beat, e.channel, e.kind, e.values) for e in doc.channel_events
    ]
    assert back.notes[0].track_id == "track-1"
    assert back.duration_beats == 2
    assert back.metadata["import_warnings"] == []


def test_unretained_midi_content_is_reported() -> None:
    mid = mido.MidiFile()
    mid.tracks.append(mido.MidiTrack([mido.MetaMessage("lyrics", text="example")]))
    stream = BytesIO()
    mid.save(file=stream)
    assert "lyrics" in str(loads_midi(stream.getvalue()).metadata["import_warnings"])


def test_preview_applies_tempo_sustain_and_produces_audible_pcm(tmp_path: Path) -> None:
    doc = _score([_note("a", 69, 0, 1)])
    doc.tempos = [TempoEvent(0, 120), TempoEvent(1, 60)]
    doc.channel_events = [MidiChannelEvent("track-0", 0, 0, "control_change", (64, 127)),
                          MidiChannelEvent("track-0", 3, 0, "control_change", (64, 0))]
    assert sounding_end(doc, doc.notes[0]) == 3
    assert beat_to_seconds(doc, 3) == 2.5
    result = render_score(doc, tmp_path / "pedal.wav", backend="preview", sample_rate=22050)
    with wave.open(result.path) as audio:
        assert audio.getnframes() / audio.getframerate() == pytest.approx(2.9, abs=1 / 22050)
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
    assert np.max(np.abs(samples)) > 1000
    assert np.sqrt(np.mean(samples[22050:33075].astype(float) ** 2)) > 100
    # The same held note, released without pedal, is silent by this point.
    dry = replace(doc, channel_events=[])
    dry_result = render_score(dry, tmp_path / "dry.wav", backend="preview", sample_rate=22050)
    with wave.open(dry_result.path) as audio:
        assert audio.getnframes() / audio.getframerate() == pytest.approx(0.9, abs=1 / 22050)


def test_one_attack_experiment_preserves_other_material_and_audio_changes(tmp_path: Path) -> None:
    doc = _score([_note("a", 60, 0), _note("b", 64, 2, 2)])
    doc.channel_events = [MidiChannelEvent("track-0", 0, 0, "control_change", (64, 0))]
    result = shift_note_onset(doc, Region(0, 4), note_id="b", shift_beats=-0.5)
    assert doc.notes[1].onset_beats == 2
    assert result.document.notes[0] == doc.notes[0]
    assert result.document.notes[1] == replace(doc.notes[1], onset_beats=1.5)
    assert result.document.channel_events == doc.channel_events
    assert result.document.id != doc.id
    a = render_score(doc, tmp_path / "a.wav", backend="preview")
    b = render_score(result.document, tmp_path / "b.wav", backend="preview")
    assert Path(a.path).read_bytes() != Path(b.path).read_bytes()
    with pytest.raises(ValueError, match="inside"):
        shift_note_onset(doc, Region(0, 4), note_id="b", shift_beats=2)


@pytest.mark.parametrize("value", [None, True, "nan", "inf"])
def test_transform_rejects_missing_and_nonfinite_parameters(value: str | bool | None) -> None:
    params: dict[str, str | int | float | bool] = {} if value is None else {"factor": value}
    request = TransformRequest("source", Region(0, 4), "rhythmic_scaling", params, [], [], "exp")
    with pytest.raises(ValueError):
        apply_transform(_score([_note("a", 60, 0)]), request)


def test_adjacent_notes_do_not_create_false_hand_span_warning() -> None:
    doc = _score([_note("a", 21, 0), _note("b", 108, 1)])
    assert validate_document(doc).warnings == []
