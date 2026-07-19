"""Top-level Phonolite window.

Wires together:

  AudioInputStream ─▶ MainWindow._on_frame (queued slot, GUI thread)
                            │
                            ▼
                       STFT.analyze
                            │
                            ├─▶ SpectrumPlot.update_spectrum
                            │     └─▶ (decaying max-hold buffer)
                            │
                            ├─▶ SpectrogramView.add_spectrum (waterfall)
                            │
                            └─▶ detect_peaks on max-hold buffer
                                  └─▶ describe_frequency
                                       (note + cents panel)

Peak detection runs against the **max-hold** buffer, not the raw frame, so
transient noise spikes don't trigger spurious notes. The waterfall adds a
time dimension that lets the eye verify which peaks are sustained.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from phonolite.audio.input_stream import AudioInputStream
from phonolite.dsp.peaks import Peak, detect_peaks
from phonolite.dsp.pitch.peak_fundamental import fundamental_from_peaks
from phonolite.dsp.stft import STFT
from phonolite.music.naming import describe_frequency
from phonolite.ui.widgets.spectrogram_view import SpectrogramView
from phonolite.ui.widgets.spectrum_plot import SpectrumPlot


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Phonolite — Real-time Spectrum Explorer")
        self.resize(1280, 900)

        # --- DSP / audio config -------------------------------------------------
        self.sample_rate = 44100
        self.window_size = 2048        # ~46 ms at 44.1 kHz
        self.fft_hop = self.window_size  # Phase 1: no overlap (Phase 2 will fix)

        self.stft = STFT(self.sample_rate, self.window_size)
        self.audio = AudioInputStream(
            sample_rate=self.sample_rate,
            block_size=self.window_size,
        )
        self.audio.frame_ready.connect(self._on_frame)

        # --- UI -----------------------------------------------------------------
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Top bar: transport + big note readout
        top = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.setFixedWidth(80)
        self.start_btn.clicked.connect(self._toggle_stream)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setFixedWidth(70)
        self.reset_btn.setToolTip("Clear max-hold trace and waterfall buffer.")
        self.reset_btn.clicked.connect(self._reset_overlays)

        self.device_label = QLabel(self._device_status_text())
        self.device_label.setStyleSheet("color: #888;")

        self.note_label = QLabel("—")
        self.note_label.setAlignment(Qt.AlignCenter)
        self.note_label.setStyleSheet(
            "font-size: 64pt; font-weight: 600; color: #E69F00;"
        )
        self.cents_label = QLabel("")
        self.cents_label.setAlignment(Qt.AlignCenter)
        self.cents_label.setStyleSheet("font-size: 16pt; color: #aaa;")

        top.addWidget(self.start_btn)
        top.addWidget(self.reset_btn)
        top.addWidget(self.device_label)
        top.addStretch(1)
        top.addWidget(self.note_label, stretch=2)
        top.addStretch(1)
        # Spacer to visually balance the left-side controls.
        top.addSpacing(80 + 70 + 12 + 2)
        root.addLayout(top)

        root.addWidget(self.cents_label)
        root.addWidget(self._separator())

        # Spectrum + spectrogram in a vertical splitter.
        self.spectrum = SpectrumPlot(decay_db_per_sec=6.0)
        self.spectrogram = SpectrogramView(
            sample_rate=self.sample_rate,
            n_fft=self.window_size,
            history_seconds=5.0,
            target_fps=30.0,
        )

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.spectrum)
        splitter.addWidget(self.spectrogram)
        splitter.setSizes([360, 360])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        root.addWidget(splitter, stretch=1)

        # Peak list (text)
        self.peak_label = QLabel("Top peaks: —")
        self.peak_label.setStyleSheet("font-family: Consolas, monospace; color: #ccc;")
        self.peak_label.setMinimumHeight(90)
        self.peak_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        root.addWidget(self.peak_label)

        self._running = False

    # --- helpers --------------------------------------------------------------

    def _device_status_text(self) -> str:
        try:
            dev = AudioInputStream.default_input_device()
            return f"device: {dev['name']}  ({dev['default_samplerate']:.0f} Hz)"
        except Exception as exc:  # noqa: BLE001
            return f"device: unavailable ({exc})"

    def _separator(self) -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #333;")
        return line

    # --- transport ------------------------------------------------------------

    def _toggle_stream(self) -> None:
        if self._running:
            self.audio.stop()
            self.start_btn.setText("Start")
            self._running = False
            self.note_label.setText("—")
            self.cents_label.setText("")
            self.peak_label.setText("Top peaks: —")
            self.spectrum.clear_view()
            self.spectrogram.clear_view()
        else:
            try:
                self.audio.start()
            except Exception as exc:  # noqa: BLE001
                self.peak_label.setText(f"Failed to open stream:\n{exc}")
                return
            self.start_btn.setText("Stop")
            self._running = True

    def _reset_overlays(self) -> None:
        """Clear the max-hold trace and waterfall history without stopping audio."""
        self.spectrum.reset_maxhold()
        self.spectrogram.clear_view()

    # --- DSP pipeline (GUI thread via queued signal) --------------------------

    def _on_frame(self, samples: object) -> None:
        block = np.asarray(samples, dtype=np.float32)
        if block.shape != (self.window_size,):
            # Drop short blocks (e.g. on stream stop). Overlap is Phase 2.
            return

        spectrum = self.stft.analyze(block.astype(np.float64))

        # Update live + max-hold spectrum, then push to the waterfall.
        self.spectrum.update_spectrum(spectrum.freqs, spectrum.magnitude_db)
        self.spectrogram.add_spectrum(spectrum.freqs, spectrum.magnitude_db)

        # Run peak detection on the max-hold buffer — much more noise-robust
        # than the live frame, because transient spikes decay away before
        # they reach the prominence threshold.
        maxhold = self.spectrum.maxhold_data()
        peak_source_db = maxhold if maxhold is not None else spectrum.magnitude_db
        peaks = detect_peaks(
            spectrum.freqs,
            peak_source_db,
            min_prominence_db=10.0,  # lower than MVP because max-hold is cleaner
            max_peaks=6,
        )

        self.spectrum.update_peaks(peaks)
        self._update_note_panel(peaks)
        self._update_peak_panel(peaks)

    def _update_note_panel(self, peaks: list[Peak]) -> None:
        if not peaks:
            self.note_label.setText("—")
            self.cents_label.setText("")
            return
        fundamental = fundamental_from_peaks(peaks, max_fundamental_hz=1500.0)
        if fundamental is None:
            self.note_label.setText("—")
            self.cents_label.setText("")
            return
        info = describe_frequency(fundamental.freq)
        if info.in_tune:
            color = "#56B4E9"
        elif abs(info.cents_deviation) <= 25.0:
            color = "#E69F00"
        else:
            color = "#888"
        self.note_label.setText(info.name)
        self.note_label.setStyleSheet(
            f"font-size: 64pt; font-weight: 600; color: {color};"
        )
        self.cents_label.setText(
            f"{info.frequency:.1f} Hz   "
            f"{info.cents_deviation:+.1f} cents"
        )

    def _update_peak_panel(self, peaks: list[Peak]) -> None:
        if not peaks:
            self.peak_label.setText("Top peaks: (none above prominence threshold)")
            return
        lines = ["Top peaks (from max-hold trace):"]
        for i, p in enumerate(peaks, 1):
            try:
                info = describe_frequency(p.freq)
                note_str = f"{info.name} {info.cents_deviation:+5.1f}c"
            except ValueError:
                note_str = "—"
            lines.append(
                f"  #{i}  {p.freq:7.1f} Hz   {p.magnitude_db:6.1f} dB   {note_str}"
            )
        self.peak_label.setText("\n".join(lines))

    # --- shutdown -------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._running:
            self.audio.stop()
        super().closeEvent(event)
