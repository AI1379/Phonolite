"""Rolling piano-roll spectrogram (MIDI-resolution waterfall).

Distinct from :class:`SpectrogramView`, which uses log-spaced Hz bins:
this view uses **one bin per semitone** on the MIDI scale, with note
names labelled on the y-axis. Purpose-built for transcription:

  • Each sustained note = a horizontal bright stripe at its exact MIDI
    position, so chord voicings, octave doublings, and inversions are
    directly readable.
  • Octave information is preserved (unlike chroma).
  • Modulations show up as vertical shifts of the whole stripe pattern.
  • Chromatic / non-diatonic notes appear as "extra" stripes between
    the in-key ones.

The grid is computed from the same max-hold spectrum the rest of the
pipeline uses, so transient noise doesn't paint fake notes. Linear
magnitudes from :func:`compute_pitch_grid` are normalised per-frame to
the strongest note, then converted to dB so colours are perceptually
meaningful and the display stays consistent across input levels.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from phonolite.dsp.chroma import PITCH_CLASS_NAMES
from phonolite.dsp.pitch_grid import compute_pitch_grid
from phonolite.ui.widgets.spectrogram_view import _build_inferno_lut

_BG = "#141414"
_FG = "#d0d0d0"

DEFAULT_HISTORY_SECONDS = 10.0
DEFAULT_TARGET_FPS = 30.0

# Display dynamic range in dB *below the per-frame peak*. 60 dB means a
# note 60 dB quieter than the loudest note in the same frame just
# touches the colour-map floor.
DEFAULT_DB_FLOOR = -60.0
DEFAULT_DB_CEIL = 0.0


def midi_to_name(midi: int) -> str:
    """MIDI note → name like 'C4', 'A#3', 'F#5' (scientific pitch notation)."""
    pc = midi % 12
    octave = midi // 12 - 1
    return f"{PITCH_CLASS_NAMES[pc]}{octave}"


class PianoRollView(pg.PlotWidget):
    """Rolling waterfall with semitone y-resolution, for transcription."""

    # Emitted when the user clicks on the waterfall. ``time_offset`` is in
    # seconds relative to "now" (negative = past, 0 = current frame).
    # The host window can use this to seek a file player back to the
    # clicked point — the core transcription scrub workflow.
    clicked_at_time = Signal(float)

    def __init__(
        self,
        midi_min: int = 36,
        midi_max: int = 96,
        history_seconds: float = DEFAULT_HISTORY_SECONDS,
        target_fps: float = DEFAULT_TARGET_FPS,
        db_floor: float = DEFAULT_DB_FLOOR,
        db_ceil: float = DEFAULT_DB_CEIL,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setBackground(_BG)
        self.setLabel("bottom", "Time (ago)", units="s")
        self.setLabel("left", "Note")
        self.showGrid(x=True, y=False, alpha=0.2)
        self.setXRange(-history_seconds, 0)

        if midi_max <= midi_min:
            raise ValueError(f"midi_max ({midi_max}) must be > midi_min ({midi_min})")
        self.midi_min = midi_min
        self.midi_max = midi_max
        self.n_notes = midi_max - midi_min + 1
        self.history_seconds = history_seconds
        self.db_floor = db_floor
        self.db_ceil = db_ceil

        self.n_cols = max(1, int(round(history_seconds * target_fps)))
        self.buffer = np.full(
            (self.n_notes, self.n_cols), db_floor, dtype=np.float32
        )

        # Octave boundary lines drawn behind the image for visual reference.
        self._octave_lines = []
        for midi in range(midi_min, midi_max + 1):
            if midi % 12 == 0:  # every C
                idx = midi - midi_min
                line = pg.InfiniteLine(
                    pos=float(idx),
                    angle=0,
                    pen=pg.mkPen("#3a3a3a", style=Qt.SolidLine, width=1),
                )
                self.addItem(line)
                self._octave_lines.append(line)

        self.image_item = pg.ImageItem(axisOrder="row-major")
        self.image_item.setLookupTable(_build_inferno_lut(256))
        self.image_item.setLevels([db_floor, db_ceil])
        self.addItem(self.image_item)

        # setImage BEFORE setRect — otherwise ImageItem.width()/height()
        # return None and the rect's scale silently becomes 1, showing a
        # single pixel stretched across the whole view.
        self.image_item.setImage(self.buffer, autoLevels=False)
        self.image_item.setRect(
            -history_seconds, 0.0, history_seconds, float(self.n_notes)
        )

        # Lock the view to the image's extent so the user can pan/zoom
        # without losing the note labels off-screen.
        self.setLimits(
            xMin=-history_seconds,
            xMax=0.0,
            yMin=0.0,
            yMax=float(self.n_notes),
        )
        self.setXRange(-history_seconds, 0.0, padding=0)
        self.setYRange(0.0, float(self.n_notes), padding=0)

        self._configure_y_axis()

    def _configure_y_axis(self) -> None:
        """Label every C with its octave (C2, C3, ...) and every G with a
        smaller tick — enough orientation to read any note at a glance."""
        major_ticks = []
        minor_ticks = []
        for midi in range(self.midi_min, self.midi_max + 1):
            idx = midi - self.midi_min
            pc = midi % 12
            octave = midi // 12 - 1
            if pc == 0:
                major_ticks.append((float(idx), f"C{octave}"))
            elif pc == 7:
                minor_ticks.append((float(idx), f"G{octave}"))
        self.getAxis("left").setTicks([major_ticks, minor_ticks])

    def add_spectrum(self, freqs: np.ndarray, magnitude_db: np.ndarray) -> None:
        """Project one frame's spectrum onto the MIDI grid and scroll it in."""
        grid = compute_pitch_grid(
            freqs,
            magnitude_db,
            midi_min=self.midi_min,
            midi_max=self.midi_max,
            silence_threshold_db=self.db_floor,
        )

        # Per-frame normalisation: the strongest note lands at db_ceil,
        # quieter notes show relative to it. This keeps the display
        # meaningful regardless of overall input level.
        peak = float(grid.max())
        if peak > 0:
            grid_db = 20.0 * np.log10(grid / peak + 1e-10)
        else:
            grid_db = np.full(self.n_notes, self.db_floor, dtype=np.float64)
        np.clip(grid_db, self.db_floor, self.db_ceil, out=grid_db)

        # Shift buffer left, append the new column on the right.
        self.buffer[:, :-1] = self.buffer[:, 1:]
        self.buffer[:, -1] = grid_db.astype(np.float32, copy=False)

        self.image_item.setImage(self.buffer, autoLevels=False)

    def clear_view(self) -> None:
        self.buffer.fill(self.db_floor)
        self.image_item.setImage(self.buffer, autoLevels=False)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            vb = self.getViewBox()
            pos = vb.mapSceneToView(ev.scenePos())
            t = float(pos.x())
            # Only emit if inside the chart area (not axis labels / margins).
            if -self.history_seconds <= t <= 0:
                self.clicked_at_time.emit(t)
        super().mousePressEvent(ev)
