"""Generate an eight-second MIDI-waterfall video for local playback checks.

The notes and audio are synthetic fixtures. This does not infer notes from video.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from music_core.io.midi import load_midi
from music_core.timing import beat_to_seconds
from reference_audio_demo import main as write_audio
from workbench_server.video import _executable


def frame_at(time: float, notes: list[tuple[int, float, float, str]]) -> NDArray[np.uint8]:
    image = np.empty((360, 640, 3), dtype=np.uint8)
    image[:] = (17, 25, 40)
    for pitch in range(36, 85):
        x = 14 + (pitch - 36) * 12
        black = pitch % 12 in (1, 3, 6, 8, 10)
        active = any(p == pitch and start <= time < end for p, start, end, _ in notes)
        image[300:350, x:x + 11] = (100, 196, 217) if active else (35, 45, 60) if black else (209, 218, 231)
    image[296:300, 14:602] = (107, 153, 201)
    for pitch, start, end, track in notes:
        if not 36 <= pitch <= 84:
            continue
        top = round(298 - (end - time) * 100)
        bottom = round(298 - (start - time) * 100)
        top, bottom = max(0, top), min(296, bottom)
        if top < bottom:
            x = 14 + (pitch - 36) * 12
            image[top:bottom, x:x + 10] = (98, 185, 228) if track == "track-0" else (232, 183, 105)
    return image


def main() -> None:
    write_audio()
    folder = Path(__file__).parent
    score = load_midi(folder / "music_lab_demo.mid")
    notes = [(note.pitch, 1 + beat_to_seconds(score, note.onset_beats),
              1 + beat_to_seconds(score, note.offset_beats), note.track_id) for note in score.notes]
    output = folder / "reference_video_demo.mp4"
    process = subprocess.Popen([
        _executable("ffmpeg"), "-nostdin", "-v", "error", "-y", "-f", "rawvideo",
        "-pixel_format", "rgb24", "-video_size", "640x360", "-framerate", "24", "-i", "pipe:0",
        "-i", str(folder / "reference_audio_demo.wav"), "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-movflags", "+faststart", "-t", "8", str(output),
    ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
    try:
        if process.stdin is None:
            raise RuntimeError("video encoder stdin unavailable")
        for index in range(8 * 24):
            process.stdin.write(frame_at(index / 24, notes).tobytes())
        process.stdin.close()
        if process.wait(timeout=60) != 0:
            raise RuntimeError("video encoder failed")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    print(output.resolve())


if __name__ == "__main__":
    main()
