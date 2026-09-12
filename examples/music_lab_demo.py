"""Write an eight-bar piano study for manual Workbench acceptance testing.

Run from the repository root: uv run python examples/music_lab_demo.py
The generated example is original synthetic test material, not a user score.
"""

from __future__ import annotations

from pathlib import Path

from music_core.io.midi import dump_midi
from music_core.ir import MeterEvent, MidiChannelEvent, NoteEvent, ScoreDocument, TempoEvent


def main() -> None:
    doc = ScoreDocument("music-lab-demo", 480, tempos=[TempoEvent(0, 80), TempoEvent(16, 96)],
                        meters=[MeterEvent(0, 4, 4)],
                        metadata={"track_names": {"track-0": "Left hand", "track-1": "Melody"}})
    chords = ((48, 52, 55), (45, 48, 52), (41, 45, 48), (43, 47, 50, 53))
    melody = ((72, 76, 79, 76), (69, 72, 76, 72), (65, 69, 72, 69), (67, 71, 74, 77))
    for bar in range(8):
        onset = bar * 4.0
        for index, pitch in enumerate(chords[bar // 2]):
            doc.notes.append(NoteEvent(f"chord-{bar}-{index}", "track-0", pitch, onset, 3.5, 68, channel=0))
        for beat, pitch in enumerate(melody[bar // 2]):
            doc.notes.append(NoteEvent(f"melody-{bar}-{beat}", "track-1", pitch, onset + beat, 0.75,
                                       90 if beat == 0 else 78, channel=0))
        doc.channel_events.extend([
            MidiChannelEvent("track-0", onset, 0, "control_change", (64, 127)),
            MidiChannelEvent("track-0", onset + 3.9, 0, "control_change", (64, 0)),
        ])
    path = Path(__file__).with_suffix(".mid")
    dump_midi(doc, path)
    print(path.resolve())


if __name__ == "__main__":
    main()
