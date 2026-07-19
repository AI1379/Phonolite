"""Rolling spectrogram (waterfall) widget.

Time on x-axis, log-frequency on y-axis, magnitude in dB as colour. Lets
the eye instantly distinguish **sustained tones** (horizontal bright
stripes) from **transient noise** (scattered specks) — directly addressing
the MVP's "noise gets picked as peaks" problem.

The frequency axis is log-spaced (so we can see 30 Hz to 16 kHz in one
view) but rendered as evenly-spaced image rows; y-axis ticks are labelled
manually with real Hz values.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

_BG = "#141414"
_FG = "#d0d0d0"

DEFAULT_F_MIN = 30.0
DEFAULT_F_MAX = 16000.0
DEFAULT_N_FREQ_BINS = 256
DEFAULT_HISTORY_SECONDS = 5.0
DEFAULT_TARGET_FPS = 30.0

# Reference frequencies for y-axis tick labels.
_Y_TICK_FREQS = [30, 50, 100, 200, 500, 1000, 2000, 5000, 10000]


def _build_inferno_lut(n: int = 256) -> np.ndarray:
    """Approximation of matplotlib's inferno colormap as an (n, 4) RGBA LUT.

    Built from hand so we don't pull in matplotlib as a dependency.
    """
    stops = np.array([0.00, 0.20, 0.40, 0.60, 0.80, 1.00])
    # Approximate inferno control points (linearly interpolated RGB).
    colors = np.array(
        [
            [0,   0,   4],
            [40,  11,  84],
            [101, 21,  110],
            [159, 42,  99],
            [212, 72,  66],
            [252, 252, 164],
        ],
        dtype=np.float64,
    )
    t = np.linspace(0.0, 1.0, n)
    lut = np.zeros((n, 3), dtype=np.uint8)
    for c in range(3):
        lut[:, c] = np.clip(np.interp(t, stops, colors[:, c]), 0, 255).astype(np.uint8)
    # pyqtgraph expects (N, 4) with alpha
    rgba = np.zeros((n, 4), dtype=np.uint8)
    rgba[:, :3] = lut
    rgba[:, 3] = 255
    return rgba


class SpectrogramView(pg.PlotWidget):
    """Rolling waterfall spectrogram, log-frequency × time, dB as colour."""

    def __init__(
        self,
        sample_rate: int,
        n_fft: int,
        history_seconds: float = DEFAULT_HISTORY_SECONDS,
        target_fps: float = DEFAULT_TARGET_FPS,
        f_min: float = DEFAULT_F_MIN,
        f_max: float = DEFAULT_F_MAX,
        n_freq_bins: int = DEFAULT_N_FREQ_BINS,
        db_floor: float = -90.0,
        db_ceil: float = -10.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setBackground(_BG)
        self.setLabel("bottom", "Time (ago)", units="s")
        self.setLabel("left", "Frequency", units="Hz")
        self.showGrid(x=True, y=False, alpha=0.2)
        self.setXRange(-history_seconds, 0)

        self.sample_rate = sample_rate
        self.n_fft = n_fft
        self.f_min = f_min
        self.f_max = f_max
        self.n_freq_bins = n_freq_bins
        self.history_seconds = history_seconds
        self.db_floor = db_floor
        self.db_ceil = db_ceil

        # Log-spaced frequency grid; rendered as evenly-spaced image rows.
        self.freq_grid = np.logspace(
            np.log10(f_min), np.log10(f_max), n_freq_bins
        )
        self._log_freq_grid = np.log10(self.freq_grid)

        self.n_cols = max(1, int(round(history_seconds * target_fps)))
        self.buffer = np.full(
            (n_freq_bins, self.n_cols), db_floor, dtype=np.float32
        )

        # ImageItem: row-major → axis 0 (freq) maps to y, axis 1 (time) to x.
        self.image_item = pg.ImageItem(axisOrder="row-major")
        self.image_item.setLookupTable(_build_inferno_lut(256))
        self.image_item.setLevels([db_floor, db_ceil])
        # Map buffer pixels to plot coords:
        #   x ∈ [-history_seconds, 0]
        #   y ∈ [0, n_freq_bins]  (relabeled via custom ticks)
        self.image_item.setRect(
            -history_seconds, 0.0, history_seconds, float(n_freq_bins)
        )
        self.addItem(self.image_item)

        self._configure_y_axis()

    def _configure_y_axis(self) -> None:
        """Replace the y-axis ticks with manually positioned Hz labels."""
        ticks = []
        span = np.log10(self.f_max) - np.log10(self.f_min)
        for f in _Y_TICK_FREQS:
            if self.f_min <= f <= self.f_max:
                idx = (np.log10(f) - np.log10(self.f_min)) / span * (
                    self.n_freq_bins - 1
                )
                label = f"{f/1000:g}k" if f >= 1000 else f"{f:g}"
                ticks.append((float(idx), label))
        self.getAxis("left").setTicks([ticks])

    def add_spectrum(self, freqs: np.ndarray, magnitude_db: np.ndarray) -> None:
        """Push one spectrum frame into the rolling buffer and refresh the image."""
        # Interpolate magnitude (linear in dB) along log-frequency onto our grid.
        log_f = np.log10(np.maximum(freqs, 1e-6))
        interp = np.interp(
            self._log_freq_grid,
            log_f,
            magnitude_db,
            left=self.db_floor,
            right=self.db_floor,
        )
        np.clip(interp, self.db_floor, self.db_ceil, out=interp)

        # Shift buffer left in-place; append new column at the right edge.
        self.buffer[:, :-1] = self.buffer[:, 1:]
        self.buffer[:, -1] = interp.astype(np.float32, copy=False)

        self.image_item.setImage(self.buffer, autoLevels=False)

    def clear_view(self) -> None:
        self.buffer.fill(self.db_floor)
        self.image_item.setImage(self.buffer, autoLevels=False)
