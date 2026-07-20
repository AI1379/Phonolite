"""Real-time chroma (pitch-class) display as 12 vertical bars.

Designed for polyphonic / orchestral input where the per-peak readout on
the spectrum panel becomes unreadable: this view collapses the spectrum
to *which notes are sounding*, regardless of octave, which makes chords
and key content visible at a glance.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from phonolite.dsp.chroma import PITCH_CLASS_NAMES

_BG = "#141414"
_FG = "#d0d0d0"
_BAR_COLOR = "#3a6a8a"   # dim default
_TOP_COLOR = "#E69F00"   # strongest pitch classes get highlighted

# Highlight the top-N bars to make chord content pop out visually.
_TOP_N_HIGHLIGHT = 3
_HIGHLIGHT_THRESHOLD = 0.3   # don't highlight "top 3" if all are weak


class ChromaView(pg.PlotWidget):
    """12-bar pitch-class histogram, normalised to max bar = 1.0."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setBackground(_BG)
        self.setLabel("bottom", "Pitch class")
        self.setLabel("left", "Normalised energy")
        self.setYRange(0, 1.08)
        self.setXRange(-0.5, 11.5)
        self.showGrid(x=False, y=True, alpha=0.2)

        ticks = [[(i, PITCH_CLASS_NAMES[i]) for i in range(12)]]
        self.getAxis("bottom").setTicks(ticks)

        # Two layered BarGraphItems: dim base + bright highlight for the
        # strongest pitch classes. Updating two items is cheaper than
        # rebuilding brushes per-bar.
        bar_width = 0.8
        bar_x = np.arange(12, dtype=np.float64) - bar_width / 2

        self._base_bars = pg.BarGraphItem(
            x=bar_x,
            height=np.zeros(12),
            width=bar_width,
            brush=pg.mkBrush(_BAR_COLOR),
            pen=pg.mkPen("#0e0e0e", width=0.5),
        )
        self.addItem(self._base_bars)

        self._highlight_bars = pg.BarGraphItem(
            x=bar_x,
            height=np.zeros(12),
            width=bar_width,
            brush=pg.mkBrush(_TOP_COLOR),
            pen=pg.mkPen("#1a1a1a", width=0.5),
        )
        self.addItem(self._highlight_bars)

    def update_chroma(self, chroma: np.ndarray) -> None:
        """Render a new chroma frame. Top-N strongest classes are highlighted.

        ``chroma`` is expected to be a length-12 vector; values are clamped to
        [0, 1] for display. Any normalisation scheme (max=1, sum=1, fixed dB
        range) works as long as it produces values in that range.
        """
        if chroma.shape != (12,):
            raise ValueError(f"chroma must have shape (12,), got {chroma.shape}")

        clamped = np.clip(chroma, 0.0, 1.0)

        # Determine which pitch classes count as "top" for this frame.
        # If everything is silent (max < threshold), nothing gets highlighted.
        if clamped.max() < _HIGHLIGHT_THRESHOLD:
            highlight_heights = np.zeros(12)
        else:
            order = np.argsort(clamped)[::-1][:_TOP_N_HIGHLIGHT]
            mask = np.zeros(12, dtype=bool)
            mask[order] = True
            highlight_heights = np.where(mask, clamped, 0.0)

        base_heights = clamped - highlight_heights

        self._base_bars.setOpts(height=base_heights)
        self._highlight_bars.setOpts(height=highlight_heights)

    def clear_view(self) -> None:
        zeros = np.zeros(12)
        self._base_bars.setOpts(height=zeros)
        self._highlight_bars.setOpts(height=zeros)
