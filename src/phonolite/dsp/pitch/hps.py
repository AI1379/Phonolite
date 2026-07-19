"""Harmonic Product Spectrum fundamental frequency estimation.

TODO(Phase 2): multiply the magnitude spectrum by downsampled copies of
itself (decimated by 2, 3, 4, ...). Peaks belonging to a harmonic series
reinforce the fundamental bin, making HPS robust to missing fundamentals
and partial harmonic series — ideal for bells, bowls, and animal sounds.
"""

from __future__ import annotations

from typing import Optional

import numpy as np


def hps(
    magnitude: np.ndarray,
    sample_rate: int,
    n_fft: int,
    harmonics: int = 8,
) -> Optional[float]:
    """Placeholder — returns ``None`` until Phase 2."""
    raise NotImplementedError("HPS lands in Phase 2")
