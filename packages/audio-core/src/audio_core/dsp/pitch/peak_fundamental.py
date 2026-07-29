"""Peak-based fundamental frequency guess.

This is NOT a real pitch detector — it just picks the strongest peak below
a configurable cutoff. For pure tones, whistles, and clearly-harmonic sounds
this coincides with the fundamental. For inharmonic or polyphonic sounds it
will be wrong; that's exactly what Phase 2 (YIN, HPS, harmonic fit) is for.

We expose it now so the MVP has *something* to feed the note display.
"""

from __future__ import annotations

from typing import Optional

from audio_core.dsp.peaks import Peak


def fundamental_from_peaks(
    peaks: list[Peak],
    max_fundamental_hz: float = 1000.0,
) -> Optional[Peak]:
    """Return the strongest peak whose frequency is at most ``max_fundamental_hz``.

    Heuristic only; treat results with skepticism on complex sounds.
    """
    candidates = [p for p in peaks if p.freq <= max_fundamental_hz]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.magnitude_db)
