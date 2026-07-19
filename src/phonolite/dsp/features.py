"""Spectral descriptors that are meaningful even when pitch is not.

TODO(Phase 2/3): these let Phonolite say something useful about drums,
wind, water and other inharmonic / noise-like sounds where a single "note"
label would be misleading.

Planned features:
  - spectral_centroid       — perceived brightness
  - spectral_flatness       — noise-likeness (0 = tonal, 1 = white noise)
  - spectral_crest / rolloff — energy concentration
  - inharmonicity           — deviation of peaks from a harmonic grid
  - pitch_confidence        — agreement across YIN / HPS / peak algorithms
"""

from __future__ import annotations

import numpy as np


def spectral_centroid(freqs: np.ndarray, magnitude: np.ndarray) -> float:
    """First moment of the magnitude spectrum. Brightness proxy."""
    mag = np.asarray(magnitude, dtype=np.float64)
    total = mag.sum()
    if total <= 0:
        return 0.0
    return float(np.dot(freqs, mag) / total)


def spectral_flatness(magnitude: np.ndarray, eps: float = 1e-12) -> float:
    """Geometric/arithmetic mean ratio in [0, 1]. 1 ⇒ white noise."""
    mag = np.asarray(magnitude, dtype=np.float64)
    mag = mag + eps
    geom = np.exp(np.mean(np.log(mag)))
    arith = np.mean(mag)
    if arith <= 0:
        return 0.0
    return float(min(1.0, geom / arith))
