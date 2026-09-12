"""Deterministic reference-tone WAV preview with tempo, velocity and sustain.

This lightweight additive synthesizer is for comparing note/rhythm experiments,
not instrument emulation. It uses a fixed gain (never per-file normalization).
Unsupported expression stays in exported MIDI and is explicitly reported here.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

from music_core.ir import NoteEvent, ScoreDocument
from music_core.timing import beat_to_seconds
from music_core.validation import validate_note


def sounding_end(doc: ScoreDocument, note: NoteEvent) -> float:
    """Extend a released key until CC64 pedal-up on its MIDI channel."""
    channel = note.channel or 0
    controls = sorted((event for event in doc.channel_events
                       if event.channel == channel and event.kind == "control_change"
                       and event.values[0] == 64), key=lambda event: (event.beat, event.order))
    down = False
    for event in controls:
        if event.beat <= note.offset_beats:
            down = event.values[1] >= 64
        elif down and event.values[1] < 64:
            return event.beat
        elif not down:
            break
    return max(note.offset_beats, doc.duration_beats) if down else note.offset_beats


def render_preview(doc: ScoreDocument, path: Path, sample_rate: int) -> list[str]:
    """Write a mono PCM16 WAV; reject unreasonable spans before allocation."""
    if not 8000 <= sample_rate <= 96000:
        raise ValueError("preview sample rate must be between 8000 and 96000 Hz")
    if len(doc.notes) > 20_000:
        raise ValueError("preview supports at most 20000 notes; select a shorter score")
    release = 0.4
    duration = beat_to_seconds(doc, doc.duration_beats) + release
    if not math.isfinite(duration) or duration > 300:
        raise ValueError("preview supports at most five minutes; export MIDI for longer scores")
    scheduled: list[tuple[NoteEvent, float, float]] = []
    for note in doc.notes:
        errors = validate_note(note).errors
        if errors or not all(math.isfinite(v) for v in (note.onset_beats, note.duration_beats)):
            raise ValueError(f"cannot preview invalid note {note.id}: {errors}")
        if note.duration_beats <= 0 or note.velocity == 0:
            continue
        start = beat_to_seconds(doc, note.onset_beats)
        end = beat_to_seconds(doc, sounding_end(doc, note))
        scheduled.append((note, start, end))
    if sum(end - start + release for _, start, end in scheduled) > 4000:
        raise ValueError("preview note density exceeds the rendering limit; export MIDI instead")
    signal = np.zeros(max(1, math.ceil(duration * sample_rate)), dtype=np.float64)
    for note, start, end in scheduled:
        offset = round(start * sample_rate)
        stop = min(len(signal), math.ceil((end + release) * sample_rate))
        t = np.arange(stop - offset, dtype=np.float64) / sample_rate
        frequency = 440.0 * 2.0 ** ((note.pitch - 69) / 12.0)
        tone = np.zeros_like(t)
        for harmonic, gain in ((1, 1.0), (2, 0.35), (3, 0.18), (4, 0.09)):
            if harmonic * frequency < sample_rate / 2:
                tone += gain * np.sin(2 * np.pi * harmonic * frequency * t)
        envelope = np.minimum(t / 0.008, 1.0) * np.exp(-t / 2.5)
        envelope *= np.exp(-np.maximum(t - (end - start), 0.0) / 0.065)
        signal[offset:stop] += tone * envelope * (note.velocity / 127.0) * 0.085
    pcm = (np.tanh(signal) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    warnings = ["Reference-tone preview: tempo, velocity and sustain are rendered with a fixed timbre and gain; this is not a piano sample library."]
    ignored = sorted({event.kind for event in doc.channel_events
                      if event.kind != "control_change" or event.values[0] != 64})
    if ignored:
        warnings.append(f"Preview ignores expression/instrument events: {', '.join(ignored)}. MIDI export retains them.")
    if any(note.channel == 9 for note in doc.notes):
        warnings.append("Percussion channel is previewed with pitched reference tones.")
    return warnings
