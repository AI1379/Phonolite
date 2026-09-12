"""Decode reference audio at the application boundary, retaining original bytes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Literal, cast

import numpy as np
from numpy.typing import NDArray
import soundfile as sf

from audio_core.dsp.waveform import waveform_peaks
from music_core.reference import AlignmentAnchor


@dataclass(frozen=True)
class ReferenceRecord:
    id: str
    filename: str
    sha256: str
    duration_seconds: float
    sample_rate: int
    channels: int
    original_token: str
    playback_token: str | None
    peaks: list[tuple[float, float]]
    anchors: tuple[AlignmentAnchor, ...] = ()
    media_kind: Literal["audio", "video"] = "audio"
    video_token: str | None = None
    video_width: int | None = None
    video_height: int | None = None
    has_audio: bool = True
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedReference:
    filename: str
    sha256: str
    duration_seconds: float
    sample_rate: int
    channels: int
    original: bytes
    playback: bytes | None
    peaks: list[tuple[float, float]]
    media_kind: Literal["audio", "video"] = "audio"
    video: bytes | None = None
    video_width: int | None = None
    video_height: int | None = None
    has_audio: bool = True
    warnings: tuple[str, ...] = ()


def prepare_audio(data: bytes, filename: str) -> PreparedReference:
    if not data or len(data) > 64 * 1024 * 1024:
        raise ValueError("reference audio must be nonempty and at most 64 MB")
    try:
        with sf.SoundFile(BytesIO(data)) as source:
            rate, channels, frames = int(source.samplerate), int(source.channels), int(source.frames)
            if not 8000 <= rate <= 192000 or channels not in (1, 2) or frames <= 0:
                raise ValueError("reference requires mono/stereo audio at 8..192 kHz")
            duration = frames / rate
            if duration > 600 or frames * channels > 40_000_000:
                raise ValueError("reference exceeds ten minutes or the decoded sample limit; import a shorter excerpt")
            samples = cast(NDArray[np.float64], source.read(dtype="float64", always_2d=True))
    except (sf.LibsndfileError, RuntimeError) as exc:
        raise ValueError("Cannot decode this audio. Use WAV, FLAC, OGG or MP3 supported by libsndfile.") from exc
    peaks = waveform_peaks(samples)
    stream = BytesIO()
    sf.write(stream, samples, rate, format="WAV", subtype="PCM_16")
    clean_name = filename.replace("\\", "/").rsplit("/", 1)[-1].replace("\r", "").replace("\n", "") or "reference.audio"
    return PreparedReference(clean_name, hashlib.sha256(data).hexdigest(), duration, rate, channels,
                         data, stream.getvalue(), peaks)
