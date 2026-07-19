"""Spectral peak detection with sub-bin frequency refinement.

Parabolic interpolation around the magnitude peak gives ~10x better
frequency precision than the raw FFT bin width — important for low notes
where the bin width (e.g. 21 Hz at 44.1k/2048) is a large fraction of a
semitone.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks


@dataclass
class Peak:
    freq: float           # refined via parabolic interpolation, in Hz
    magnitude_db: float
    bin_index: int
    bin_offset: float     # fractional bin offset in [-0.5, 0.5]


def parabolic_refine(magnitude: np.ndarray, idx: int) -> tuple[float, float]:
    """Quadratic peak interpolation.

    Returns (fractional_bin_offset, refined_magnitude). On a log-magnitude
    spectrum this is the standard interpolation; on linear magnitude it is
    still correct as long as the peak is well above noise.
    """
    if idx <= 0 or idx >= len(magnitude) - 1:
        return 0.0, float(magnitude[idx])
    y0 = magnitude[idx - 1]
    y1 = magnitude[idx]
    y2 = magnitude[idx + 1]
    denom = (y0 - 2 * y1 + y2)
    if denom == 0:
        return 0.0, float(y1)
    offset = 0.5 * (y0 - y2) / denom
    refined = y1 - 0.25 * (y0 - y2) * offset
    return float(offset), float(refined)


def detect_peaks(
    freqs: np.ndarray,
    magnitude_db: np.ndarray,
    min_prominence_db: float = 12.0,
    max_peaks: int = 8,
    min_freq: float = 20.0,
) -> list[Peak]:
    """Detect the most prominent spectral peaks and refine their frequencies."""
    # Mask out sub-audible bins before peak search.
    audible = magnitude_db.copy()
    audible[freqs < min_freq] = -np.inf

    indices, props = find_peaks(audible, prominence=min_prominence_db)
    if len(indices) == 0:
        return []

    proms = props["prominences"]
    order = np.argsort(proms)[::-1][:max_peaks]

    peaks: list[Peak] = []
    bin_width = float(freqs[1] - freqs[0]) if len(freqs) > 1 else 1.0
    for idx in indices[order]:
        offset, refined_mag = parabolic_refine(magnitude_db, idx)
        freq = float(freqs[idx]) + offset * bin_width
        peaks.append(
            Peak(
                freq=freq,
                magnitude_db=refined_mag,
                bin_index=int(idx),
                bin_offset=offset,
            )
        )

    peaks.sort(key=lambda p: p.magnitude_db, reverse=True)
    return peaks
