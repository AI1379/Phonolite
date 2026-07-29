"""MIDI-resolution pitch grid (a.k.a. log-frequency spectrogram bins).

Same linear-interpolation distribution trick as :mod:`audio_core.dsp.chroma`,
but WITHOUT the mod-12 fold — every semitone from ``midi_min`` to
``midi_max`` keeps its own bucket. This is the basis of the piano-roll
waterfall view used for transcription, where octave information matters.

Output is a length ``(midi_max - midi_min + 1)`` vector of *linear*
magnitudes (sum of FFT-bin magnitudes whose frequency maps to each MIDI
note). The caller is expected to convert to dB or normalise as needed.
"""

from __future__ import annotations

import numpy as np

A4_FREQ = 440.0
A4_MIDI = 69

# Covers C2 (~65 Hz, cello C, bass guitar low) up to C6 (~1 kHz, violin /
# flute high). Wider than this and the y-axis gets cramped.
DEFAULT_MIDI_MIN = 36   # C2
DEFAULT_MIDI_MAX = 96   # C6

# Same silence guard as chroma: avoids phantom readings on no input.
DEFAULT_SILENCE_THRESHOLD_DB = -60.0


def compute_pitch_grid(
    freqs: np.ndarray,
    magnitude_db: np.ndarray,
    midi_min: int = DEFAULT_MIDI_MIN,
    midi_max: int = DEFAULT_MIDI_MAX,
    a4: float = A4_FREQ,
    silence_threshold_db: float = DEFAULT_SILENCE_THRESHOLD_DB,
) -> np.ndarray:
    """Project a magnitude spectrum onto the MIDI semitone grid.

    Returns a length ``(midi_max - midi_min + 1)`` array of linear
    magnitudes per semitone. Silent input (peak below the threshold)
    returns a zero vector.
    """
    n_notes = midi_max - midi_min + 1
    if n_notes <= 0:
        return np.zeros(0, dtype=np.float64)
    if freqs.size == 0 or magnitude_db.size == 0:
        return np.zeros(n_notes, dtype=np.float64)

    # Restrict to the MIDI range's frequency span — padded by half a
    # semitone on each side so that FFT bins whose centre frequency sits
    # just below midi_min (or just above midi_max) still contribute their
    # main-lobe energy to the boundary MIDI notes. Without this padding,
    # a low note like C2 (65.4 Hz) lands at bin 3 of a 2048-sample FFT
    # and gets cut off entirely.
    f_min = a4 * 2.0 ** ((midi_min - 0.5 - A4_MIDI) / 12.0)
    f_max = a4 * 2.0 ** ((midi_max + 0.5 - A4_MIDI) / 12.0)
    mask = (freqs >= f_min) & (freqs <= f_max)
    f = freqs[mask]
    db = magnitude_db[mask]
    if f.size == 0 or float(db.max()) < silence_threshold_db:
        return np.zeros(n_notes, dtype=np.float64)

    # dB → linear magnitude.
    mag = np.power(10.0, db / 20.0)

    # Exact (float) MIDI note per bin, then linear-interpolated distribution
    # between the two nearest integer MIDI notes (same rationale as chroma).
    midi_float = A4_MIDI + 12.0 * np.log2(f / a4)
    midi_floor = np.floor(midi_float).astype(np.int64)
    frac = midi_float - midi_floor

    grid = np.zeros(n_notes, dtype=np.float64)
    lo_idx = midi_floor - midi_min
    hi_idx = midi_floor + 1 - midi_min

    lo_valid = (lo_idx >= 0) & (lo_idx < n_notes)
    np.add.at(grid, lo_idx[lo_valid], (mag * (1.0 - frac))[lo_valid])

    hi_valid = (hi_idx >= 0) & (hi_idx < n_notes)
    np.add.at(grid, hi_idx[hi_valid], (mag * frac)[hi_valid])

    return grid


def top_midi_notes(
    grid: np.ndarray,
    midi_min: int,
    k: int = 5,
    threshold_ratio: float = 0.25,
) -> list[tuple[int, float]]:
    """Return the ``k`` strongest MIDI notes above ``threshold_ratio * max``.

    ``threshold_ratio`` is relative to the grid's max, so weak frames don't
    return a list of "top 5 of nothing". Pairs are ``(midi_note, value)``.
    """
    if grid.size == 0:
        return []
    peak = float(grid.max())
    if peak <= 0:
        return []
    cutoff = peak * threshold_ratio
    candidates = [(int(midi_min + i), float(grid[i]))
                  for i in range(grid.size) if grid[i] >= cutoff]
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[:k]
