"""Top-level Phonolite window.

Supports two interchangeable audio sources, both feeding the same
``frame_ready`` slot so the analysis pipeline is identical:

  • ``AudioInputStream`` — live microphone (44.1 kHz default).
  • ``AudioFilePlayer``  — any libsndfile-supported file, played through
                           the speakers at its native sample rate.

When the file source is active the mic stream is stopped, and vice versa.
Switching sources may change the pipeline sample rate (e.g. 44.1 kHz mic →
48 kHz file); the STFT is rebuilt and the max-hold / waterfall are reset.

Pipeline:

  AudioSource.frame_ready ─▶ MainWindow._on_frame (queued, GUI thread)
                                   │
                                   ▼
                               STFT.analyze
                                   │
                                   ├─▶ SpectrumPlot.update_spectrum
                                   │     └─▶ (decaying max-hold buffer)
                                   │
                                   ├─▶ SpectrogramView.add_spectrum (Hz waterfall)
                                   │
                                   ├─▶ PianoRollView.add_spectrum (MIDI waterfall)
                                   │
                                   ├─▶ detect_peaks on max-hold ─▶ note + cents
                                   │
                                   └─▶ compute_chroma / top_midi_notes (text + bars)
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from phonolite.audio.file_player import AudioFilePlayer
from phonolite.audio.input_stream import AudioInputStream
from phonolite.dsp.chroma import compute_chroma, top_pitch_classes
from phonolite.dsp.peaks import Peak, detect_peaks
from phonolite.dsp.pitch.peak_fundamental import fundamental_from_peaks
from phonolite.dsp.pitch_grid import compute_pitch_grid, top_midi_notes
from phonolite.dsp.stft import STFT
from phonolite.music.naming import describe_frequency
from phonolite.ui.widgets.chroma_view import ChromaView
from phonolite.ui.widgets.piano_roll_view import PianoRollView, midi_to_name
from phonolite.ui.widgets.spectrogram_view import SpectrogramView
from phonolite.ui.widgets.spectrum_plot import SpectrumPlot


class _PanelWrapper(QWidget):
    """Thin header bar + plot widget, with a maximize toggle button.

    Lays out the plot as the primary content area and a 22 px header
    strip that shows the panel name and a small ``Max`` / ``Restore``
    button. When maximised the button text flips and the wrapper can
    be collapsed by an external controller.
    """

    def __init__(
        self, title: str, widget: QWidget, on_maximize, parent=None
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # ----- header -----------------------------------------------------------
        header = QWidget()
        header.setFixedHeight(22)
        header.setStyleSheet("background: #222;")
        hdr = QHBoxLayout(header)
        hdr.setContentsMargins(6, 0, 2, 0)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("color: #999; font-size: 10pt; background: transparent;")

        self._max_btn = QPushButton("Max")
        self._max_btn.setFixedSize(44, 18)
        self._max_btn.setStyleSheet(
            "QPushButton { background: #333; border: none; color: #aaa; "
            "font-size: 8pt; } "
            "QPushButton:hover { background: #555; color: #fff; }"
        )
        self._max_btn.clicked.connect(lambda: on_maximize(self))

        hdr.addWidget(title_lbl)
        hdr.addStretch()
        hdr.addWidget(self._max_btn)
        layout.addWidget(header)

        # ----- panel body -------------------------------------------------------
        layout.addWidget(widget, stretch=1)
        self._widget = widget
        self._maximized = False

    def set_maximized(self, maximized: bool) -> None:
        self._maximized = maximized
        self._max_btn.setText("Restore" if maximized else "Max")

MIC_SAMPLE_RATE = 44100
FILE_DIALOG_FILTER = (
    "Audio Files (*.wav *.flac *.ogg *.mp3 *.opus *.aif *.aiff *.m4a);;"
    "All Files (*.*)"
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Phonolite — Real-time Spectrum Explorer")
        self.resize(1280, 900)

        # --- DSP / audio config -------------------------------------------------
        self.default_sample_rate = MIC_SAMPLE_RATE
        self.sample_rate = MIC_SAMPLE_RATE
        self.window_size = 2048

        self.stft = STFT(self.sample_rate, self.window_size)

        # Microphone source (always available).
        self.audio = AudioInputStream(
            sample_rate=self.default_sample_rate,
            block_size=self.window_size,
        )
        self.audio.frame_ready.connect(self._on_frame)

        # File source (created on demand).
        self.file_player: Optional[AudioFilePlayer] = None

        # Source state.
        self._mic_running = False
        self._source_mode = "mic"   # 'mic' or 'file'

        # --- UI -----------------------------------------------------------------
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        root.addLayout(self._build_top_bar())
        root.addWidget(self.cents_label)
        root.addWidget(self._separator())

        # File transport row (hidden until a file is loaded).
        self.file_transport = self._build_file_transport()
        root.addWidget(self.file_transport)
        self.file_transport.setVisible(False)

        # Spectrum + spectrogram + chroma + piano-roll in a vertical splitter.
        self.spectrum = SpectrumPlot(decay_db_per_sec=6.0)
        self.spectrogram = SpectrogramView(
            sample_rate=self.sample_rate,
            n_fft=self.window_size,
            history_seconds=5.0,
            target_fps=30.0,
        )
        self.chroma = ChromaView()
        self.piano_roll = PianoRollView(
            midi_min=36,   # C2
            midi_max=96,   # C6
            history_seconds=10.0,
            target_fps=30.0,
        )

        # Click on the piano-roll waterfall → seek the file player to that
        # point (the core transcription scrub workflow).
        self.piano_roll.clicked_at_time.connect(self._on_waterfall_click)

        # Wrap each plot in a _PanelWrapper so the user can maximise one
        # view to fill the entire grid area.
        self._panel_wrappers = [
            _PanelWrapper("Spectrum",     self.spectrum,     self._toggle_maximize),
            _PanelWrapper("Spectrogram",  self.spectrogram,  self._toggle_maximize),
            _PanelWrapper("Piano Roll",   self.piano_roll,   self._toggle_maximize),
            _PanelWrapper("Chroma",       self.chroma,       self._toggle_maximize),
        ]

        top_row = QSplitter(Qt.Horizontal)
        top_row.addWidget(self._panel_wrappers[0])
        top_row.addWidget(self._panel_wrappers[1])

        bottom_row = QSplitter(Qt.Horizontal)
        bottom_row.addWidget(self._panel_wrappers[2])
        bottom_row.addWidget(self._panel_wrappers[3])

        self._panel_splitter = QSplitter(Qt.Vertical)
        self._panel_splitter.addWidget(top_row)
        self._panel_splitter.addWidget(bottom_row)
        # Top row ~25 %, bottom ~75 % — piano-roll is the transcription
        # workhorse and deserves most of the space.
        self._panel_splitter.setSizes([160, 400])
        top_row.setSizes([240, 240])
        bottom_row.setSizes([400, 200])
        self._top_row = top_row
        self._bottom_row = bottom_row

        self._maximized_index: Optional[int] = None
        self._saved_sizes: Optional[dict] = None

        root.addWidget(self._panel_splitter, stretch=1)

        # Peak list (text)
        self.peak_label = QLabel("Top peaks: —")
        self.peak_label.setStyleSheet("font-family: Consolas, monospace; color: #ccc;")
        self.peak_label.setMinimumHeight(90)
        self.peak_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        root.addWidget(self.peak_label)

        self._refresh_source_label()

    # --- UI construction ------------------------------------------------------

    def _build_top_bar(self) -> QHBoxLayout:
        top = QHBoxLayout()

        self.start_btn = QPushButton("Start Mic")
        self.start_btn.setFixedWidth(90)
        self.start_btn.setToolTip("Toggle live microphone input.")
        self.start_btn.clicked.connect(self._toggle_mic)

        self.open_file_btn = QPushButton("Open File…")
        self.open_file_btn.clicked.connect(self._open_file_dialog)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setFixedWidth(70)
        self.reset_btn.setToolTip("Clear max-hold trace and waterfall buffer.")
        self.reset_btn.clicked.connect(self._reset_overlays)

        self.source_label = QLabel("")
        self.source_label.setStyleSheet("color: #888;")

        self.note_label = QLabel("—")
        self.note_label.setAlignment(Qt.AlignCenter)
        self.note_label.setStyleSheet(
            "font-size: 64pt; font-weight: 600; color: #E69F00;"
        )
        self.cents_label = QLabel("")
        self.cents_label.setAlignment(Qt.AlignCenter)
        self.cents_label.setStyleSheet("font-size: 16pt; color: #aaa;")

        top.addWidget(self.start_btn)
        top.addWidget(self.open_file_btn)
        top.addWidget(self.reset_btn)
        top.addWidget(self.source_label)
        top.addStretch(1)
        top.addWidget(self.note_label, stretch=2)
        top.addStretch(1)
        # Spacer balances the left-side control cluster visually.
        top.addSpacing(90 + 80 + 12 + 4)
        return top

    def _build_file_transport(self) -> QWidget:
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)

        self.play_pause_btn = QPushButton("Pause")
        self.play_pause_btn.setFixedWidth(80)
        self.play_pause_btn.clicked.connect(self._toggle_playback)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedWidth(70)
        self.stop_btn.setToolTip("Stop and unload the current file.")
        self.stop_btn.clicked.connect(self._close_file)

        self.filename_label = QLabel("")
        self.filename_label.setStyleSheet(
            "color: #aaa; font-family: Consolas, monospace;"
        )

        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setMinimum(0)
        self.position_slider.setMaximum(1000)
        # sliderMoved fires only on user drag, avoiding a feedback loop with
        # the programmatic value updates we drive from position_changed.
        self.position_slider.sliderMoved.connect(self._on_slider_seek)

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setStyleSheet(
            "color: #ccc; font-family: Consolas, monospace;"
        )
        self.time_label.setMinimumWidth(110)

        h.addWidget(self.play_pause_btn)
        h.addWidget(self.stop_btn)
        h.addWidget(self.filename_label, stretch=2)
        h.addWidget(self.position_slider, stretch=4)
        h.addWidget(self.time_label)
        return bar

    # --- helpers --------------------------------------------------------------

    def _separator(self) -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #333;")
        return line

    @staticmethod
    def _format_time(seconds: float) -> str:
        s = max(0, int(round(seconds)))
        return f"{s // 60}:{s % 60:02d}"

    def _refresh_source_label(self) -> None:
        try:
            dev = AudioInputStream.default_input_device()
            mic_text = f"mic: {dev['name']} ({self.default_sample_rate} Hz)"
        except Exception:  # noqa: BLE001
            mic_text = f"mic: unavailable ({self.default_sample_rate} Hz)"
        if self._source_mode == "file" and self.file_player is not None:
            self.source_label.setText(
                f"▶ {self.file_player.file_path.name}  "
                f"({self.file_player.sample_rate} Hz, "
                f"{self.file_player.channels}ch)"
            )
        else:
            self.source_label.setText(mic_text)

    def _set_sample_rate(self, rate: int) -> None:
        if rate == self.sample_rate:
            return
        self.sample_rate = rate
        self.stft = STFT(rate, self.window_size)
        # Bins changed → max-hold and waterfall must be rebuilt from scratch.
        self.spectrum.reset_maxhold()
        self.spectrogram.clear_view()

    # --- mic transport --------------------------------------------------------

    def _toggle_mic(self) -> None:
        if self._mic_running:
            self.audio.stop()
            self._mic_running = False
            self.start_btn.setText("Start Mic")
            self._clear_readouts()
        else:
            # Mic and file are mutually exclusive.
            if self._source_mode == "file":
                self._close_file()
            try:
                self.audio.start()
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Microphone", f"Failed to open stream:\n{exc}")
                return
            self._mic_running = True
            self._source_mode = "mic"
            self.start_btn.setText("Stop Mic")
            self._set_sample_rate(self.default_sample_rate)
            self._refresh_source_label()

    # --- file transport -------------------------------------------------------

    def _open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Audio File", "", FILE_DIALOG_FILTER
        )
        if not path:
            return
        self._load_file(path)

    def _load_file(self, path: str) -> None:
        # Tear down any active source first.
        if self._mic_running:
            self.audio.stop()
            self._mic_running = False
            self.start_btn.setText("Start Mic")
        if self.file_player is not None:
            self._disconnect_file_player()
            self.file_player.stop()

        try:
            self.file_player = AudioFilePlayer(path, block_size=self.window_size)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Open File", f"Failed to open file:\n{exc}")
            self.file_player = None
            return

        self._source_mode = "file"
        self._set_sample_rate(self.file_player.sample_rate)

        # Wire signals.
        self.file_player.frame_ready.connect(self._on_frame)
        self.file_player.state_changed.connect(self._on_file_state_changed)
        self.file_player.position_changed.connect(self._on_position_changed)

        # Configure transport UI.
        self.filename_label.setText(self.file_player.file_path.name)
        self.position_slider.setValue(0)
        self.time_label.setText(
            f"0:00 / {self._format_time(self.file_player.duration)}"
        )
        self.play_pause_btn.setText("Pause")
        self.file_transport.setVisible(True)
        self._clear_readouts()
        self._refresh_source_label()

        # Auto-start playback.
        self.file_player.play()

    def _close_file(self) -> None:
        if self.file_player is None:
            return
        self._disconnect_file_player()
        self.file_player.stop()
        self.file_player = None
        self._source_mode = "mic"
        self.file_transport.setVisible(False)
        self._set_sample_rate(self.default_sample_rate)
        self._clear_readouts()
        self._refresh_source_label()

    def _disconnect_file_player(self) -> None:
        if self.file_player is None:
            return
        try:
            self.file_player.frame_ready.disconnect(self._on_frame)
        except RuntimeError:
            pass  # already disconnected
        try:
            self.file_player.state_changed.disconnect(self._on_file_state_changed)
        except RuntimeError:
            pass
        try:
            self.file_player.position_changed.disconnect(self._on_position_changed)
        except RuntimeError:
            pass

    def _toggle_playback(self) -> None:
        if self.file_player is None:
            return
        if self.file_player.state == "playing":
            self.file_player.pause()
        else:
            self.file_player.play()

    def _on_file_state_changed(self, state: str) -> None:
        if state == "playing":
            self.play_pause_btn.setText("Pause")
        elif state == "paused":
            self.play_pause_btn.setText("Play")
        elif state == "finished":
            self.play_pause_btn.setText("Replay")
        elif state == "stopped":
            # File closed externally — leave UI to _close_file.
            pass

    def _on_position_changed(self, seconds: float) -> None:
        if self.file_player is None or self.file_player.duration <= 0:
            return
        ratio = max(0.0, min(seconds / self.file_player.duration, 1.0))
        # Block signals to avoid sliderMoved firing back into seek().
        was_blocked = self.position_slider.blockSignals(True)
        self.position_slider.setValue(int(ratio * 1000))
        self.position_slider.blockSignals(was_blocked)
        self.time_label.setText(
            f"{self._format_time(seconds)} / "
            f"{self._format_time(self.file_player.duration)}"
        )

    def _on_slider_seek(self, slider_value: int) -> None:
        if self.file_player is None or self.file_player.duration <= 0:
            return
        seconds = slider_value / 1000.0 * self.file_player.duration
        self.file_player.seek(seconds)

    # --- maximise / restore grid ------------------------------------------------

    def _toggle_maximize(self, wrapper: _PanelWrapper) -> None:
        """Called when a ``Max`` / ``Restore`` button is clicked."""
        try:
            idx = self._panel_wrappers.index(wrapper)
        except ValueError:
            return
        if self._maximized_index == idx:
            self._restore_panels()
        else:
            self._maximize_panel(idx)

    def _maximize_panel(self, idx: int) -> None:
        self._saved_sizes = {
            "main": list(self._panel_splitter.sizes()),
            "top": list(self._top_row.sizes()),
            "bottom": list(self._bottom_row.sizes()),
        }
        for i, w in enumerate(self._panel_wrappers):
            w.setVisible(i == idx)
            w.set_maximized(i == idx)
        self._maximized_index = idx

    def _restore_panels(self) -> None:
        if self._saved_sizes is None:
            return
        for w in self._panel_wrappers:
            w.setVisible(True)
            w.set_maximized(False)
        self._maximized_index = None
        self._panel_splitter.setSizes(self._saved_sizes["main"])
        self._top_row.setSizes(self._saved_sizes["top"])
        self._bottom_row.setSizes(self._saved_sizes["bottom"])
        self._saved_sizes = None

    # --- waterfall click → seek -------------------------------------------------

    def _on_waterfall_click(self, time_offset: float) -> None:
        """Seek the file player to the clicked waterfall column.

        ``time_offset`` is in seconds relative to *now* (negative = past).
        """
        if self.file_player is None or self.file_player.state == "stopped":
            return
        new_pos = self.file_player.position + time_offset
        if new_pos < 0:
            new_pos = 0.0
        self.file_player.seek(new_pos)
        # If paused, auto-play so the user hears the replayed section.
        if self.file_player.state == "paused":
            self.file_player.play()

    # --- shared ---------------------------------------------------------------

    def _reset_overlays(self) -> None:
        """Clear max-hold and waterfall without affecting the active source."""
        self.spectrum.reset_maxhold()
        self.spectrogram.clear_view()
        self.piano_roll.clear_view()

    def _clear_readouts(self) -> None:
        self.note_label.setText("—")
        self.cents_label.setText("")
        self.peak_label.setText("Top peaks: —")
        self.spectrum.clear_view()
        self.spectrogram.clear_view()
        self.piano_roll.clear_view()
        self.chroma.clear_view()

    # --- DSP pipeline (GUI thread via queued signal) --------------------------

    def _on_frame(self, samples: object) -> None:
        block = np.asarray(samples, dtype=np.float32)
        if block.shape != (self.window_size,):
            # Drop short blocks (e.g. partial read at file EOF).
            return

        spectrum = self.stft.analyze(block.astype(np.float64))

        self.spectrum.update_spectrum(spectrum.freqs, spectrum.magnitude_db)
        self.spectrogram.add_spectrum(spectrum.freqs, spectrum.magnitude_db)

        maxhold = self.spectrum.maxhold_data()
        peak_source_db = maxhold if maxhold is not None else spectrum.magnitude_db
        peaks = detect_peaks(
            spectrum.freqs,
            peak_source_db,
            min_prominence_db=10.0,
            max_peaks=6,
        )

        self.spectrum.update_peaks(peaks)
        self._update_note_panel(peaks)
        self._update_peak_panel(peaks)
        self._update_chroma_panel(spectrum.freqs, peak_source_db)
        # Piano-roll and "active notes" readout both use the max-hold
        # buffer — same noise-rejection as chroma and peak detection.
        self.piano_roll.add_spectrum(spectrum.freqs, peak_source_db)

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

        # Dense-polyphony summaries: top MIDI notes (with octave) + top
        # pitch classes. These are the lines a transcriber actually reads.
        try:
            maxhold = self.spectrum.maxhold_data()
            if maxhold is not None:
                grid = compute_pitch_grid(self.stft._freqs, maxhold)
                top_notes = top_midi_notes(grid, midi_min=36, k=6, threshold_ratio=0.3)
                if top_notes:
                    names = " ".join(midi_to_name(m) for m, _ in top_notes)
                    lines.append(f"  active notes: {names}")
        except Exception:
            pass

        try:
            maxhold = self.spectrum.maxhold_data()
            if maxhold is not None:
                from phonolite.dsp.chroma import PITCH_CLASS_NAMES
                chroma = compute_chroma(self.stft._freqs, maxhold)
                top3 = top_pitch_classes(chroma, k=3)
                if chroma.max() > 0.3:
                    names = " ".join(PITCH_CLASS_NAMES[i] for i, _ in top3)
                    lines.append(f"  chroma top-3: {names}")
        except Exception:
            pass
        self.peak_label.setText("\n".join(lines))

    def _update_chroma_panel(self, freqs: np.ndarray, magnitude_db: np.ndarray) -> None:
        """Compute chroma from the max-hold buffer and refresh the bars."""
        chroma = compute_chroma(freqs, magnitude_db)
        self.chroma.update_chroma(chroma)

    # --- shutdown -------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._mic_running:
            self.audio.stop()
        if self.file_player is not None:
            self.file_player.stop()
        super().closeEvent(event)
