"""Lock-free ring buffer with configurable hop/overlap.

TODO(Phase 2): replace the simple "one block == one FFT window" scheme used
in Phase 1 with a proper ring buffer that supports overlapping STFT windows
(e.g. 75% overlap), so low-frequency pitch tracking improves and the
spectrogram waterfall is smooth.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


class RingBuffer:
    """Fixed-capacity sample ring used to feed overlapping windows.

    Not yet wired into the live pipeline; placeholder for Phase 2.
    """

    def __init__(
        self,
        capacity: int,
        dtype: type[np.float32] | np.dtype[np.float32] = np.float32,
    ) -> None:
        self.capacity = capacity
        self._buf = np.zeros(capacity, dtype=dtype)
        self._write = 0
        self._filled = 0

    def push(self, samples: NDArray[np.float32]) -> None:
        n = len(samples)
        if n >= self.capacity:
            self._buf[:] = samples[-self.capacity:]
            self._write = 0
            self._filled = self.capacity
            return
        end = (self._write + n) % self.capacity
        if end < self._write:
            split = self.capacity - self._write
            self._buf[self._write:] = samples[:split]
            self._buf[:end] = samples[split:]
        else:
            self._buf[self._write:end] = samples
        self._write = end
        self._filled = min(self.capacity, self._filled + n)

    def latest(self, n: int) -> NDArray[np.float32]:
        if n > self.capacity:
            raise ValueError(f"requested {n} > capacity {self.capacity}")
        start = (self._write - n) % self.capacity
        if start + n <= self.capacity:
            return self._buf[start : start + n].copy()
        split = self.capacity - start
        out = np.empty(n, dtype=self._buf.dtype)
        out[:split] = self._buf[start:]
        out[split:] = self._buf[: n - split]
        return out
