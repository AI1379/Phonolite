"""Harmonic series template matching — the "fit a fundamental" feature.

TODO(Phase 3): given the detected peak set, search a log-spaced grid of
candidate fundamentals f0 ∈ [f_min, f_max] and score how well the harmonic
series {f0, 2f0, 3f0, ...} explains the observed peaks. The best-scoring
f0 + its inharmonicity coefficient is shown alongside the per-peak readout.

This is the part that turns Phonolite from "a tuner that lies about bells"
into "a tool that tells you *how* non-harmonic a bell is".
"""

from __future__ import annotations

from dataclasses import dataclass

from typing import Optional

from audio_core.dsp.peaks import Peak


@dataclass
class HarmonicFit:
    fundamental: float
    score: float
    inharmonicity: float
    n_harmonics_matched: int


def fit_harmonic_series(peaks: list[Peak], f_min: float = 50.0, f_max: float = 2000.0) -> Optional[HarmonicFit]:
    """Placeholder — returns ``None`` until Phase 3."""
    raise NotImplementedError("Harmonic fit lands in Phase 3")
