"""Tests for render backends (design doc issue #8)."""

from __future__ import annotations

from pathlib import Path
import wave

import pytest

from music_core.ir import NoteEvent, ScoreDocument
from music_core.render import (
    FluidSynthBackend,
    MidiFileBackend,
    MuseScoreBackend,
    RenderError,
    render_score,
)


def _doc() -> ScoreDocument:
    return ScoreDocument(
        id="v", ppq=480,
        notes=[
            NoteEvent(id="n1", track_id="t", pitch=60, onset_beats=0.0, duration_beats=1.0, velocity=80),
        ],
    )


class _StubBackend:
    """Records the MIDI it receives; always available."""

    name = "stub"

    def __init__(self) -> None:
        self.last_midi: bytes | None = None
        self.rendered = False

    def is_available(self) -> bool:
        return True

    def render(self, *, midi_bytes: bytes, out_path: Path, sample_rate: int) -> list[str]:
        self.last_midi = midi_bytes
        out_path.write_bytes(b"WAV" + midi_bytes[:1])
        self.rendered = True
        return [f"sample_rate={sample_rate}"]


def test_render_score_uses_injected_backend_and_produces_midi(tmp_path: Path) -> None:
    stub = _StubBackend()
    out = tmp_path / "out.wav"
    result = render_score(_doc(), out, backend=stub)
    assert stub.rendered
    assert stub.last_midi is not None and len(stub.last_midi) > 0
    assert result.backend == "stub"
    assert result.path == str(out)
    assert result.warnings == ["sample_rate=44100"]


def test_auto_produces_audio_without_external_synth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("music_core.render._which_any", lambda _names: None)
    out = tmp_path / "out.wav"
    result = render_score(_doc(), out, backend="auto")
    assert result.backend == "preview"
    assert result.path.endswith("out.wav")
    assert Path(result.path).is_file()
    with wave.open(result.path) as audio:
        assert audio.getnframes() > 0
        assert audio.getsampwidth() == 2


def test_explicit_midi_backend_writes_mid(tmp_path: Path) -> None:
    out = tmp_path / "render.wav"
    result = render_score(_doc(), out, backend="midi")
    assert result.backend == "midi-file"
    assert Path(result.path).suffix == ".mid"
    assert Path(result.path).read_bytes()[:4] != b""  # non-empty MIDI


def test_fluidsynth_backend_reports_unavailable_without_soundfont() -> None:
    backend = FluidSynthBackend(soundfont=None)
    assert not backend.is_available()
    backend2 = FluidSynthBackend(soundfont="nope.sf2")
    assert not backend2.is_available()  # missing file


def test_musescore_backend_not_available_in_minimal_env() -> None:
    # In this environment there is no musescore/mscore on PATH.
    backend = MuseScoreBackend()
    if backend.is_available():
        pytest.skip("musescore unexpectedly present")
    out = "ignored.wav"
    with pytest.raises(RenderError):
        render_score(_doc(), out, backend="musescore")


def test_unknown_backend_raises() -> None:
    with pytest.raises(ValueError):
        render_score(_doc(), "out.wav", backend="nope")


def test_midifile_backend_is_always_available() -> None:
    assert MidiFileBackend().is_available()
