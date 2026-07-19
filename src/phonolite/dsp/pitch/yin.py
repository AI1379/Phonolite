"""YIN fundamental frequency estimator.

TODO(Phase 2): implement the de Cheveigné & Kawahara (2002) algorithm in
pure numpy. YIN is the de-facto standard for monophonic pitch detection and
handles voice / whistles / bird calls far better than the peak heuristic.

Reference:
  de Cheveigné, A., & Kawahara, H. (2002). "YIN, a fundamental frequency
  estimator for speech and music." JASA 111(4), 1917-1930.
"""

from __future__ import annotations

from typing import Optional

import numpy as np


def yin(
    samples: np.ndarray,
    sample_rate: int,
    f_min: float = 50.0,
    f_max: float = 1000.0,
    threshold: float = 0.1,
) -> Optional[float]:
    """Placeholder — returns ``None`` until Phase 2."""
    raise NotImplementedError("YIN lands in Phase 2")
