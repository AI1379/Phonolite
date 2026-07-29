"""Audio file playback with a Qt-signal bridge matching :class:`AudioInputStream`.

Loads any format supported by libsndfile (WAV, FLAC, OGG/Vorbis, Opus, MP3
on libsndfile >= 1.1.0, AIFF, ...). Plays through ``sounddevice.OutputStream``
and emits mono float32 blocks on the same ``frame_ready`` signal the live
microphone uses — so the downstream pipeline (STFT, peaks, spectrum, waterfall)
is identical between sources.

State machine:

  stopped ──play()──▶ playing ──pause()──▶ paused
     ▲                  │                     │
     │                  │ (EOF)              │
     │                  ▼                     │
     └────────────  finished ◀───────────────┘
                       │
                       │ play() restarts from 0
                       ▼
                    playing

The PortAudio callback runs on its own thread; like ``AudioInputStream`` we
keep it thin (copy + emit). All stream / file lifecycle is mutated on the
GUI thread.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import QObject, Qt, Signal


class AudioFilePlayer(QObject):
    """Play an audio file while emitting mono blocks for visualisation."""

    # Same shape as AudioInputStream.frame_ready so they're plug-and-play.
    frame_ready = Signal(object)
    state_changed = Signal(str)        # 'stopped' | 'playing' | 'paused' | 'finished'
    position_changed = Signal(float)   # seconds, emits from the audio thread

    def __init__(
        self,
        file_path: str | Path,
        block_size: int = 2048,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.file_path = Path(file_path)
        self.block_size = block_size

        # Read file metadata without keeping the handle open.
        with sf.SoundFile(str(self.file_path)) as info_file:
            self.sample_rate: int = info_file.samplerate
            self.channels: int = info_file.channels
            self._total_frames = len(info_file)
        self.duration: float = (
            self._total_frames / self.sample_rate if self.sample_rate > 0 else 0.0
        )

        self._stream: Optional[sd.OutputStream] = None
        self._file_handle: Optional[sf.SoundFile] = None
        self._state = "stopped"
        self._position_seconds = 0.0

        # When the callback detects EOF it can't safely stop the stream from
        # the audio thread; we relay through this signal and finish teardown
        # on the GUI thread.
        self.state_changed.connect(self._on_state_changed, Qt.QueuedConnection)

    # --- public state --------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def position(self) -> float:
        return self._position_seconds

    # --- transport -----------------------------------------------------------

    def play(self) -> None:
        """Start or resume playback. Restart from 0 if previously finished."""
        if self._state == "playing":
            return
        if self._state in ("stopped", "finished"):
            self._open_fresh()
            self._state = "playing"
            self.state_changed.emit(self._state)
            self._stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                blocksize=self.block_size,
                callback=self._portaudio_callback,
            )
            self._stream.start()
        elif self._state == "paused":
            self._state = "playing"
            self.state_changed.emit(self._state)
            if self._stream is not None:
                self._stream.start()

    def pause(self) -> None:
        if self._state != "playing":
            return
        if self._stream is not None:
            self._stream.stop()
        self._state = "paused"
        self.state_changed.emit(self._state)

    def stop(self) -> None:
        """Fully stop and close the file. Safe to call from any state."""
        self._teardown_stream()
        self._position_seconds = 0.0
        self._state = "stopped"
        self.state_changed.emit(self._state)
        self.position_changed.emit(self._position_seconds)

    def seek(self, seconds: float) -> None:
        """Seek to ``seconds`` (clamped to file duration). Pauses playback
        while seeking to keep the PortAudio buffer consistent."""
        target = max(0.0, min(seconds, self.duration))
        target_frame = int(target * self.sample_rate)
        was_playing = self._state == "playing"
        if self._stream is not None and was_playing:
            self._stream.stop()
        if self._file_handle is not None:
            self._file_handle.seek(target_frame)
            # If we sought past EOF, reopen the file at the right frame.
            if self._file_handle.tell() >= self._total_frames:
                self._file_handle.close()
                self._file_handle = sf.SoundFile(str(self.file_path))
                self._file_handle.seek(target_frame)
        self._position_seconds = target
        self.position_changed.emit(self._position_seconds)
        if was_playing and self._stream is not None:
            self._state = "playing"
            self._stream.start()

    # --- internals -----------------------------------------------------------

    def _open_fresh(self) -> None:
        """(Re)open the file handle at frame 0 and reset position."""
        if self._file_handle is not None:
            self._file_handle.close()
        self._file_handle = sf.SoundFile(str(self.file_path))
        self._file_handle.seek(0)
        self._position_seconds = 0.0
        self.position_changed.emit(self._position_seconds)

    def _teardown_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._file_handle is not None:
            try:
                self._file_handle.close()
            except Exception:
                pass
            self._file_handle = None

    def _on_state_changed(self, state: str) -> None:
        # The callback emits 'finished' from the audio thread when it reads
        # past EOF; tear down the stream here on the GUI thread.
        if state == "finished":
            self._teardown_stream()

    def _portaudio_callback(self, outdata, frames, time_info, status) -> None:
        if self._file_handle is None or self._state != "playing":
            outdata.fill(0)
            return

        # ``always_2d=True`` gives shape (frames_read, channels).
        chunk = self._file_handle.read(frames, dtype="float32", always_2d=True)
        read = chunk.shape[0]

        if read < frames:
            outdata[:read] = chunk
            outdata[read:].fill(0)
            self._position_seconds = self.duration
            self._state = "finished"
            # Emit signals from the audio thread; they're auto-queued to GUI.
            self.position_changed.emit(self._position_seconds)
            self.state_changed.emit(self._state)
            if chunk.shape[0] > 0:
                self.frame_ready.emit(self._to_mono(chunk))
            return

        outdata[:] = chunk
        self._position_seconds = self._file_handle.tell() / self.sample_rate
        self.position_changed.emit(self._position_seconds)
        self.frame_ready.emit(self._to_mono(chunk))

    @staticmethod
    def _to_mono(chunk: np.ndarray) -> np.ndarray:
        """Mix a (frames, channels) block down to a 1-D float32 mono block."""
        if chunk.shape[1] == 1:
            return np.ascontiguousarray(chunk[:, 0])
        return np.ascontiguousarray(chunk.mean(axis=1))
