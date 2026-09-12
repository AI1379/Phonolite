"""Bounded waveform envelopes from already-decoded samples (no audio IO)."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def waveform_peaks(samples: NDArray[np.float64], bins: int = 1600) -> list[tuple[float, float]]:
    if samples.ndim != 2 or samples.shape[0] == 0 or not 1 <= bins <= 4096:
        raise ValueError("waveform requires nonempty frames x channels and 1..4096 bins")
    if not np.isfinite(samples).all():
        raise ValueError("audio samples must be finite")
    edges = np.linspace(0, len(samples), min(bins, len(samples)) + 1, dtype=np.int64)
    return [(float(np.min(samples[left:right])), float(np.max(samples[left:right])))
            for left, right in zip(edges, edges[1:])]
