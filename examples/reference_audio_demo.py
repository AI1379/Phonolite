"""Generate local reference audio with a one-second lead-in for R1 testing."""

from __future__ import annotations

import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from music_core.io.midi import load_midi
from music_core.render import render_score
from music_lab_demo import main as write_midi


def main() -> None:
    write_midi()
    folder = Path(__file__).parent
    doc = load_midi(folder / "music_lab_demo.mid")
    output = folder / "reference_audio_demo.wav"
    with TemporaryDirectory(prefix="reference-demo-") as temporary:
        rendered = render_score(doc, Path(temporary) / "score.wav", backend="preview", sample_rate=22050)
        with wave.open(rendered.path) as source:
            rate = source.getframerate()
            frames = source.readframes(source.getnframes())
        with wave.open(str(output), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(rate)
            target.writeframes(bytes(rate * 2) + frames)
    print(output.resolve())
    print("First eight beats: audio 1.0..7.0 seconds; beat 0 is after the lead-in.")


if __name__ == "__main__":
    main()
