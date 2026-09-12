"""Waveform envelopes retain transients and stereo polarity."""

from __future__ import annotations

import numpy as np
import pytest

from audio_core.dsp.waveform import waveform_peaks


def test_stereo_envelope_does_not_cancel_opposite_polarity() -> None:
    samples = np.array([[1.0, -1.0], [0.0, 0.0], [0.25, -0.5], [0.0, 0.0]], dtype=np.float64)
    assert waveform_peaks(samples, bins=2) == [(-1.0, 1.0), (-0.5, 0.25)]


def test_silence_stays_silent_and_short_inputs_have_no_empty_bins() -> None:
    assert waveform_peaks(np.zeros((2, 1), dtype=np.float64), bins=100) == [(0.0, 0.0), (0.0, 0.0)]
    with pytest.raises(ValueError):
        waveform_peaks(np.array([[float("nan")]], dtype=np.float64))
