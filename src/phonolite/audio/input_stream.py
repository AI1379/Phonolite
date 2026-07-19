"""Microphone capture via ``sounddevice`` with a Qt-signal bridge.

The PortAudio callback runs on its own (real-time) thread. We do the minimum
work there — copy the block and emit a Qt signal. The signal is auto-queued
across threads because ``AudioInputStream`` is parented on the main thread,
so ``MainWindow``'s slot always runs on the GUI thread.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal


class AudioInputStream(QObject):
    """Wrap ``sounddevice.InputStream`` and emit mono float32 blocks."""

    # ``object`` is used deliberately so that an arbitrary ndarray can be
    # passed across threads without PySide6 needing a metatype registration.
    frame_ready = Signal(object)

    def __init__(
        self,
        sample_rate: int = 44100,
        block_size: int = 2048,
        device: Optional[int | str] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.device = device
        self._stream: Optional[sd.InputStream] = None

    # --- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            device=self.device,
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.block_size,
            callback=self._portaudio_callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is None:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None

    # --- internals -----------------------------------------------------------

    def _portaudio_callback(self, in_data, frames, time_info, status) -> None:
        # ``in_data`` is owned by PortAudio and reused — copy before emitting.
        # Shape is (frames, 1) for mono; flatten to (frames,).
        block = np.ascontiguousarray(in_data[:, 0])
        self.frame_ready.emit(block)

    # --- diagnostics ---------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._stream is not None and self._stream.active

    @staticmethod
    def list_input_devices() -> list[dict]:
        """Return all input devices visible to PortAudio."""
        devices = sd.query_devices()
        if isinstance(devices, dict):
            devices = [devices]
        return [d for d in devices if d.get("max_input_channels", 0) >= 1]

    @staticmethod
    def default_input_device() -> dict:
        return sd.query_devices(sd.default.device[0])
