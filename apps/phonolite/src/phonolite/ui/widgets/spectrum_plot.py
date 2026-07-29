"""Real-time magnitude spectrum widget with peak markers and max-hold trace.

Built on pyqtgraph for ~60 FPS updates of multi-thousand-bin curves.

The max-hold curve decays at a configurable rate (default 6 dB/s). Running
peak detection on the max-hold buffer instead of the live frame makes the
note readout ignore transient noise spikes while still tracking sustained
tones within a fraction of a second.
"""

from __future__ import annotations

import time
from typing import Iterable, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt

from audio_core.dsp.peaks import Peak

_BG = "#141414"
_FG = "#d0d0d0"
_CURVE_COLOR = "#56B4E9"      # sky blue — live frame
_MAXHOLD_COLOR = "#D55E00"    # vermilion — decaying max-hold
_PEAK_COLOR = "#E69F00"       # orange — peak markers
_LABEL_COLOR = "#F0E442"      # yellow

DEFAULT_DECAY_DB_PER_SEC = 6.0


class SpectrumPlot(pg.PlotWidget):
    """Log-frequency magnitude spectrum (dB) with overlaid peak markers."""

    def __init__(
        self,
        decay_db_per_sec: float = DEFAULT_DECAY_DB_PER_SEC,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._decay_db_per_sec = decay_db_per_sec

        pg.setConfigOptions(antialias=False, background=_BG, foreground=_FG)
        self.setBackground(_BG)
        self.setLogMode(x=True, y=False)
        self.setLabel("bottom", "Frequency", units="Hz")
        self.setLabel("left", "Magnitude", units="dB")
        self.setXRange(np.log10(20), np.log10(20000))
        self.setYRange(-90, 0)
        self.showGrid(x=True, y=True, alpha=0.25)

        # Decaying max-hold curve is drawn first so the live curve overlays it.
        self._maxhold_curve = self.plot(pen=pg.mkPen(_MAXHOLD_COLOR, width=1.0))
        self._curve = self.plot(pen=pg.mkPen(_CURVE_COLOR, width=1.2))

        self._peak_scatter = pg.ScatterPlotItem(
            size=9,
            pen=pg.mkPen("w", width=1),
            brush=pg.mkBrush(_PEAK_COLOR),
        )
        self.addItem(self._peak_scatter)
        self._peak_labels: list[pg.TextItem] = []

        # Max-hold state.
        self._maxhold_buffer: Optional[np.ndarray] = None
        self._last_update_time: Optional[float] = None

        # Reference lines at A4 octaves for orientation.
        for a_oct in (55.0, 110.0, 220.0, 440.0, 880.0, 1760.0, 3520.0):
            line = pg.InfiniteLine(
                pos=a_oct,
                angle=90,
                pen=pg.mkPen("#555", style=Qt.DashLine, width=1),
            )
            self.addItem(line)
            lbl = pg.TextItem(text=f"A{int(round(np.log2(a_oct/440)+4))}", color="#777", anchor=(1, 0))
            lbl.setPos(a_oct, -88)
            self.addItem(lbl)

    def update_spectrum(self, freqs: np.ndarray, magnitude_db: np.ndarray) -> None:
        mask = freqs >= 20.0
        self._curve.setData(freqs[mask], magnitude_db[mask])
        self._update_maxhold(freqs, magnitude_db)
        self._maxhold_curve.setData(freqs[mask], self._maxhold_buffer[mask])

    def maxhold_data(self) -> Optional[np.ndarray]:
        """Return the current max-hold buffer (same length as the last frame),
        or ``None`` if no frame has been processed yet."""
        return self._maxhold_buffer

    def reset_maxhold(self) -> None:
        self._maxhold_buffer = None
        self._last_update_time = None
        self._maxhold_curve.setData([], [])

    def update_peaks(self, peaks: Iterable[Peak]) -> None:
        for lbl in self._peak_labels:
            self.removeItem(lbl)
        self._peak_labels.clear()

        peak_list = list(peaks)
        if not peak_list:
            self._peak_scatter.setData([], [])
            return

        xs = np.array([p.freq for p in peak_list], dtype=np.float64)
        ys = np.array([p.magnitude_db for p in peak_list], dtype=np.float64)
        self._peak_scatter.setData(xs, ys)

        for p in peak_list:
            label = pg.TextItem(
                html=(f"<span style='color:{_LABEL_COLOR};font-size:9pt'>"
                      f"{p.freq:.0f} Hz</span>"),
                anchor=(0, 1),
            )
            label.setPos(p.freq, p.magnitude_db)
            self.addItem(label)
            self._peak_labels.append(label)

    def clear_view(self) -> None:
        self._curve.setData([], [])
        self._maxhold_curve.setData([], [])
        self._peak_scatter.setData([], [])
        for lbl in self._peak_labels:
            self.removeItem(lbl)
        self._peak_labels.clear()
        self.reset_maxhold()

    # --- internals -----------------------------------------------------------

    def _update_maxhold(self, freqs: np.ndarray, magnitude_db: np.ndarray) -> None:
        now = time.perf_counter()
        mag = np.asarray(magnitude_db, dtype=np.float64)

        if self._maxhold_buffer is None or len(self._maxhold_buffer) != len(mag):
            self._maxhold_buffer = mag.copy()
            self._last_update_time = now
            return

        if self._last_update_time is not None:
            dt = max(0.0, now - self._last_update_time)
            decay = self._decay_db_per_sec * dt
            decayed = self._maxhold_buffer - decay
            self._maxhold_buffer = np.maximum(decayed, mag)
        else:
            self._maxhold_buffer = np.maximum(self._maxhold_buffer, mag)
        self._last_update_time = now
