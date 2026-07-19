"""Short-time Fourier transform utilities.

Phase 1 uses a single-shot ``analyze()`` per audio block (no overlap).
Phase 2 will introduce overlapping windows via :class:`audio.ring_buffer.RingBuffer`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import windows

DB_FLOOR = 1e-10  # magnitude floor before log, avoids log(0)


@dataclass(frozen=True)
class Spectrum:
    freqs: np.ndarray        # rfftfreq bins, shape (n_fft//2 + 1,)
    magnitude: np.ndarray    # linear magnitude
    magnitude_db: np.ndarray # 20 * log10(magnitude)


class STFT:
    """Single-window magnitude spectrum analyser."""

    def __init__(
        self,
        sample_rate: int = 44100,
        window_size: int = 2048,
        window: str = "hann",
    ) -> None:
        if window_size <= 0 or window_size & (window_size - 1) != 0:
            # Non power-of-two works with numpy FFT but is slower; we just warn.
            pass
        self.sample_rate = sample_rate
        self.window_size = window_size
        # ``fftbins=True`` (periodic, DFT-even) is the correct choice for STFT.
        self._window = windows.get_window(window, window_size, fftbins=True)
        # Pre-compute bin frequencies for the default n_fft
        self._freqs = np.fft.rfftfreq(window_size, d=1.0 / sample_rate)

    @property
    def bin_width(self) -> float:
        return self.sample_rate / self.window_size

    def analyze(self, samples: np.ndarray) -> Spectrum:
        """Compute the magnitude spectrum of ``samples``.

        ``samples`` is expected to be 1-D float, length == ``window_size``.
        """
        if samples.shape != (self.window_size,):
            raise ValueError(
                f"expected ({self.window_size},) got {samples.shape}; "
                f"buffering/overlap is the caller's responsibility"
            )
        windowed = self._window * samples.astype(np.float64, copy=False)
        spectrum = np.fft.rfft(windowed, n=self.window_size)
        magnitude = np.abs(spectrum)
        magnitude_db = 20.0 * np.log10(magnitude + DB_FLOOR)
        return Spectrum(freqs=self._freqs, magnitude=magnitude, magnitude_db=magnitude_db)
