"""Frequency ↔ note name / cents / interval.

Conventions:
  - A4 == 440 Hz (configurable per-call, useful for historical temperaments).
  - MIDI note numbers follow the standard: A4 == 69, middle C (C4) == 60.
  - Octave numbering is scientific pitch notation (C4 = middle C).

All math uses 12-TET (twelve-tone equal temperament). Just-intonation
helpers (ratio → cents, ratio → interval name) are also provided so the
harmonic-series features in Phase 3 can label observed intervals directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

A4_FREQ = 440.0
A4_MIDI = 69

NOTE_NAMES_EN = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_NAMES_ZH = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# (semitone_offset, short, english, chinese)
_INTERVAL_TABLE = {
    0: ("P1", "unison", "纯一度"),
    1: ("m2", "minor second", "小二度"),
    2: ("M2", "major second", "大二度"),
    3: ("m3", "minor third", "小三度"),
    4: ("M3", "major third", "大三度"),
    5: ("P4", "perfect fourth", "纯四度"),
    6: ("A4", "tritone", "三全音"),
    7: ("P5", "perfect fifth", "纯五度"),
    8: ("m6", "minor sixth", "小六度"),
    9: ("M6", "major sixth", "大六度"),
    10: ("m7", "minor seventh", "小七度"),
    11: ("M7", "major seventh", "大七度"),
    12: ("P8", "octave", "纯八度"),
}


@dataclass(frozen=True)
class NoteInfo:
    frequency: float
    midi_float: float          # exact position on the 12-TET scale
    midi_int: int              # nearest MIDI note
    name: str                  # e.g. "A4"
    pitch_class: str           # e.g. "A"
    octave: int                # scientific pitch notation
    cents_deviation: float     # from nearest 12-TET note, in [-50, 50]
    in_tune: bool              # |cents| <= in_tune_cents


def freq_to_midi(freq: float, a4: float = A4_FREQ) -> float:
    """Continuous MIDI note number for ``freq`` Hz against reference ``a4``."""
    if freq <= 0:
        raise ValueError(f"frequency must be positive, got {freq}")
    return A4_MIDI + 12.0 * math.log2(freq / a4)


def midi_to_freq(midi: float, a4: float = A4_FREQ) -> float:
    """Inverse of :func:`freq_to_midi`."""
    return a4 * 2.0 ** ((midi - A4_MIDI) / 12.0)


def midi_to_name(midi_int: int) -> tuple[str, int]:
    """Return (pitch_class, octave) for an integer MIDI note."""
    pitch_class = NOTE_NAMES_EN[midi_int % 12]
    octave = (midi_int // 12) - 1
    return pitch_class, octave


def describe_frequency(
    freq: float,
    a4: float = A4_FREQ,
    in_tune_cents: float = 5.0,
) -> NoteInfo:
    """Full 12-TET description of ``freq`` Hz."""
    midi_f = freq_to_midi(freq, a4)
    midi_i = int(round(midi_f))
    pitch_class, octave = midi_to_name(midi_i)
    cents = (midi_f - midi_i) * 100.0
    # Wrap cents into [-50, 50] for display sanity.
    while cents > 50.0:
        cents -= 100.0
        midi_i += 1
        pitch_class, octave = midi_to_name(midi_i)
    while cents < -50.0:
        cents += 100.0
        midi_i -= 1
        pitch_class, octave = midi_to_name(midi_i)
    return NoteInfo(
        frequency=freq,
        midi_float=midi_f,
        midi_int=midi_i,
        name=f"{pitch_class}{octave}",
        pitch_class=pitch_class,
        octave=octave,
        cents_deviation=cents,
        in_tune=abs(cents) <= in_tune_cents,
    )


def cents_between(freq_low: float, freq_high: float) -> float:
    """Signed cents from ``freq_low`` to ``freq_high`` (positive = upward)."""
    return 1200.0 * math.log2(freq_high / freq_low)


def ratio_to_cents(ratio: float) -> float:
    """Cents value of a just-intonation frequency ratio (e.g. 3/2 → 701.96)."""
    return 1200.0 * math.log2(ratio)


def interval_between(freq_low: float, freq_high: float) -> tuple[str, int]:
    """Nearest named interval between two frequencies.

    Returns ``(short_name, signed_semitones)``. ``signed_semitones`` is not
    wrapped to an octave, so e.g. C4→C5 returns ("P8", +12) and C5→C4
    returns ("P8", -12). Compound intervals (>P8) get the underlying
    pitch-class label (e.g. 14 semitones → M2).
    """
    semitones = int(round(12 * math.log2(freq_high / freq_low)))
    pc = abs(semitones) % 12
    short = _INTERVAL_TABLE.get(pc, ("?", "?", "?"))[0]
    return short, semitones


def harmonic_ratio(harmonic_number: int) -> tuple[str, float]:
    """For the n-th harmonic of a fundamental, return the interval name and
    its pure-intonation ratio relative to the fundamental.

    Examples:
      n=1 → ("P1", 1/1)
      n=2 → ("P8", 2/1)
      n=3 → ("P5", 3/2)   # octave-reduced
      n=5 → ("M3", 5/4)
      n=7 → ("m7", 7/4)
    """
    if harmonic_number < 1:
        raise ValueError("harmonic number must be >= 1")
    # octave-reduce to [1, 2)
    n = harmonic_number
    while n >= 2:
        n /= 2
    # Match against low-integer just ratios for nice names.
    just_names = {
        1.0: "P1",
        16 / 15: "m2",
        9 / 8: "M2",
        6 / 5: "m3",
        5 / 4: "M3",
        4 / 3: "P4",
        7 / 5: "A4",
        3 / 2: "P5",
        8 / 5: "m6",
        5 / 3: "M6",
        7 / 4: "m7",
        15 / 8: "M7",
    }
    name = "?"
    best_err = float("inf")
    for r, lbl in just_names.items():
        err = abs(math.log2(r) - math.log2(n))
        if err < best_err:
            best_err = err
            name = lbl
    return name, harmonic_number
