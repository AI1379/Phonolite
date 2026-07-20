"""Chroma (pitch-class) features.

Project the magnitude spectrum onto the 12 equal-temperament pitch classes
(C, C#, D, ..., B), summing energy across all octaves. This collapses the
dense polyphonic spectrum of orchestral / chordal music into something
readable: instead of "what frequencies are present" you see "what *notes*
are present", which is exactly what chord and key analysis need.

Algorithm:
  For each FFT bin with frequency f (within [min_freq, max_freq]):
    1. Convert dB → linear magnitude.
    2. Compute MIDI note: midi = 69 + 12 * log2(f / A4).
    3. Round to nearest integer → pitch class = midi % 12.
    4. Add magnitude to that pitch class bucket.
  Normalise so max bucket = 1.0 for display.

We deliberately do NOT use librosa to keep dependencies light and the
math transparent. The downside vs. CQT-based chroma is that linear-FFT
bins give finer semitone resolution at low frequencies than at high ones;
for the [55, 4000] Hz range with a 2048-sample window this is acceptable.
"""

from __future__ import annotations

import numpy as np

A4_FREQ = 440.0
A4_MIDI = 69

# 12-TET pitch class names, index 0 == C.
PITCH_CLASS_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Default integration window. Below this, bins are mostly rumble/DC; above
# this, FFT bin spacing becomes coarser than a semitone and pitch-class
# assignment gets unreliable.
DEFAULT_MIN_FREQ = 55.0    # A1
DEFAULT_MAX_FREQ = 4000.0  # ~B4 fundamental, plus useful harmonics

# Inputs whose loudest bin is below this get a zero chroma vector. Without
# this guard, silence (where every bin sits at the dB floor) normalises to
# max=1.0 and the bars display a phantom "all notes present" reading.
DEFAULT_SILENCE_THRESHOLD_DB = -60.0


def compute_chroma(
    freqs: np.ndarray,
    magnitude_db: np.ndarray,
    a4: float = A4_FREQ,
    min_freq: float = DEFAULT_MIN_FREQ,
    max_freq: float = DEFAULT_MAX_FREQ,
    silence_threshold_db: float = DEFAULT_SILENCE_THRESHOLD_DB,
) -> np.ndarray:
    """Return a 12-element chroma vector (one per pitch class, index 0 == C).

    Values are normalised so the loudest pitch class == 1.0. Silent input
    (peak below ``silence_threshold_db``) returns a zero vector.
    """
    if freqs.size == 0 or magnitude_db.size == 0:
        return np.zeros(12, dtype=np.float64)

    mask = (freqs >= min_freq) & (freqs <= max_freq)
    f = freqs[mask]
    db = magnitude_db[mask]
    if f.size == 0:
        return np.zeros(12, dtype=np.float64)

    # Silence guard: avoids phantom chroma from the dB floor on no input.
    if float(db.max()) < silence_threshold_db:
        return np.zeros(12, dtype=np.float64)

    # dB → linear magnitude.
    mag = np.power(10.0, db / 20.0)

    # Compute exact (float) MIDI note per bin, then split each bin's energy
    # between its two nearest integer MIDI notes via linear interpolation.
    # This reduces "main-lobe spill into the adjacent pitch class" that
    # otherwise pollutes chroma when an instrument's fundamental sits near
    # a semitone boundary (e.g. A3 at 220 Hz has main-lobe bins landing on
    # A#3, which a naive round-to-nearest would mis-assign).
    midi_float = A4_MIDI + 12.0 * np.log2(f / a4)
    midi_floor = np.floor(midi_float).astype(np.int64)
    frac = midi_float - midi_floor  # ∈ [0, 1): weight for the upper neighbour
    pc_lower = np.mod(midi_floor, 12)
    pc_upper = np.mod(midi_floor + 1, 12)

    chroma = np.zeros(12, dtype=np.float64)
    np.add.at(chroma, pc_lower, mag * (1.0 - frac))
    np.add.at(chroma, pc_upper, mag * frac)

    peak = chroma.max()
    if peak > 0:
        chroma /= peak
    return chroma


def top_pitch_classes(chroma: np.ndarray, k: int = 3) -> list[tuple[int, float]]:
    """Return the ``k`` strongest pitch classes as ``(class_index, value)``
    pairs, sorted strongest first."""
    if chroma.shape != (12,):
        raise ValueError(f"chroma must have shape (12,), got {chroma.shape}")
    k = max(1, min(k, 12))
    order = np.argsort(chroma)[::-1][:k]
    return [(int(i), float(chroma[i])) for i in order]
