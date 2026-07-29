"""Smoke tests: the extracted audio-core package works standalone.

These guard the ``src/phonolite`` -> ``packages/audio-core`` extraction;
algorithm-specific tests should live next to their modules as they grow.
"""

from __future__ import annotations

import numpy as np

from audio_core.dsp.chroma import compute_chroma
from audio_core.dsp.ring_buffer import RingBuffer
from audio_core.dsp.stft import STFT
from audio_core.music.naming import (
    describe_frequency,
    freq_to_midi,
    midi_to_freq,
    midi_to_name,
)


def test_freq_midi_round_trip() -> None:
    assert freq_to_midi(440.0) == 69.0
    assert midi_to_freq(69.0) == 440.0
    assert midi_to_name(69) == ("A", 4)


def test_describe_frequency_a4() -> None:
    info = describe_frequency(440.0)
    assert info.name == "A4"
    assert info.pitch_class == "A"
    assert info.in_tune


def make_a4_spectrum(window_size: int = 4096, sample_rate: int = 44100):
    stft = STFT(sample_rate=sample_rate, window_size=window_size)
    t = np.arange(window_size) / sample_rate
    sine = np.sin(2.0 * np.pi * 440.0 * t).astype(np.float32)
    return stft, stft.analyze(sine)


def test_stft_finds_sine_frequency() -> None:
    stft, spectrum = make_a4_spectrum()
    peak_freq = float(spectrum.freqs[np.argmax(spectrum.magnitude)])
    assert abs(peak_freq - 440.0) < stft.bin_width


def test_chroma_of_a4_sine_highlights_pitch_class_a() -> None:
    _, spectrum = make_a4_spectrum()
    chroma = compute_chroma(spectrum.freqs, spectrum.magnitude_db)
    assert chroma.shape == (12,)
    assert int(np.argmax(chroma)) == 9  # A


def test_ring_buffer_latest_returns_ordered_tail() -> None:
    buf = RingBuffer(capacity=8)
    buf.push(np.arange(5, dtype=np.float32))
    buf.push(np.arange(5, 9, dtype=np.float32))
    assert buf.latest(4).tolist() == [5.0, 6.0, 7.0, 8.0]
