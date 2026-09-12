"""Bounded local video preparation using FFmpeg, without altering the original.

The browser plays a normalized MP4. Waveform audio is extracted from that same
preview, padded from its timestamp zero, so it shares the video's second axis.
We preserve relative audio/video timestamps rather than resetting each stream
independently. No visual note recognition is performed here.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from workbench_server.assets import PreparedReference, prepare_audio

_MAX_BYTES = 256 * 1024 * 1024
_LOCAL_FORMATS = "mov,matroska,webm,avi"


class ProbeStream(BaseModel):
    index: int = 0
    codec_type: str = ""
    width: int = 0
    height: int = 0
    disposition: dict[str, int] = Field(default_factory=dict)


class ProbeFormat(BaseModel):
    duration: str = "0"


class ProbeResult(BaseModel):
    streams: list[ProbeStream] = Field(default_factory=list)
    format: ProbeFormat = Field(default_factory=ProbeFormat)


def _executable(name: str) -> str:
    configured = os.environ.get(f"WORKBENCH_{name.upper()}", name)
    path = shutil.which(configured)
    if path is None:
        raise ValueError(f"Video import requires {name} on PATH or WORKBENCH_{name.upper()}")
    # Scoop's shim launches another process; use its real binary so a timeout
    # kills the decoder itself rather than leaving it behind after the shim.
    shim = Path(path).with_suffix(".shim")
    if os.name == "nt" and shim.is_file():
        for line in shim.read_text(encoding="utf-8").splitlines():
            if line.startswith("path = "):
                target = line.removeprefix("path = ").strip().strip('"')
                if Path(target).is_file():
                    return target
    return path


def _run(command: list[str], timeout: int) -> bytes:
    try:
        result = subprocess.run(command, capture_output=True, check=False, timeout=timeout,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"Video preparation exceeded {timeout} seconds; use a shorter clip") from exc
    except OSError as exc:
        raise ValueError("Unable to start the local video decoder") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[-1200:]
        raise ValueError(f"Video decoding failed: {detail}")
    return result.stdout


def _probe(executable: str, path: Path) -> tuple[ProbeResult, ProbeStream, float]:
    raw = _run([executable, "-v", "error", "-protocol_whitelist", "file,pipe",
                "-format_whitelist", _LOCAL_FORMATS,
                "-show_entries", "format=duration:stream=index,codec_type,width,height:stream_disposition=attached_pic",
                "-of", "json", str(path)], 20)
    try:
        result = ProbeResult.model_validate_json(raw)
        duration = float(result.format.duration)
    except (ValidationError, ValueError) as exc:
        raise ValueError("Video duration or stream metadata could not be read") from exc
    video = next((stream for stream in result.streams
                  if stream.codec_type == "video" and not stream.disposition.get("attached_pic")), None)
    if video is None:
        raise ValueError("The selected file has no video track")
    if not math.isfinite(duration) or not 0 < duration <= 600:
        raise ValueError("Video clips must have a known duration of at most ten minutes")
    if not 2 <= video.width <= 8192 or not 2 <= video.height <= 8192:
        raise ValueError("Video dimensions exceed the supported range")
    return result, video, duration


def prepare_video(data: bytes, filename: str) -> PreparedReference:
    """Keep original bytes and derive a browser MP4 plus aligned waveform audio."""
    if not data or len(data) > _MAX_BYTES:
        raise ValueError("video must be nonempty and at most 256 MB")
    ffmpeg, ffprobe = _executable("ffmpeg"), _executable("ffprobe")
    with tempfile.TemporaryDirectory(prefix="workbench-video-") as temporary:
        folder = Path(temporary)
        source, preview, audio_path = folder / "source.media", folder / "preview.mp4", folder / "audio.wav"
        source.write_bytes(data)
        _, source_video, _ = _probe(ffprobe, source)
        _run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
              "-protocol_whitelist", "file,pipe", "-format_whitelist", _LOCAL_FORMATS,
              "-copyts", "-start_at_zero", "-i", str(source),
              "-map", f"0:{source_video.index}", "-map", "0:a:0?", "-sn", "-dn",
              "-vf", "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
              "-fps_mode", "vfr", "-c:a", "aac", "-b:a", "160k", "-ac", "2",
              "-movflags", "+faststart", "-threads", "2", "-t", "600", str(preview)], 180)
        if not preview.is_file() or not 0 < preview.stat().st_size <= _MAX_BYTES:
            raise ValueError("Prepared video is empty or exceeds 256 MB; use a shorter clip")
        metadata, dimensions, duration = _probe(ffprobe, preview)
        has_audio = any(stream.codec_type == "audio" for stream in metadata.streams)
        audio: PreparedReference | None = None
        if has_audio:
            _run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                  "-protocol_whitelist", "file,pipe", "-copyts", "-start_at_zero", "-i", str(preview),
                  "-map", "0:a:0", "-vn", "-af", "aresample=async=1:first_pts=0,apad",
                  "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le", "-t", str(duration), str(audio_path)], 60)
            audio = prepare_audio(audio_path.read_bytes(), "video-audio.wav")
        clean_name = filename.replace("\\", "/").rsplit("/", 1)[-1].replace("\r", "").replace("\n", "") or "reference.video"
        return PreparedReference(
            clean_name, hashlib.sha256(data).hexdigest(), duration,
            audio.sample_rate if audio else 0, audio.channels if audio else 0,
            data, audio.playback if audio else None, audio.peaks if audio else [],
            media_kind="video", video=preview.read_bytes(), video_width=dimensions.width,
            video_height=dimensions.height, has_audio=has_audio,
            warnings=("Video has no audio track; use visual timing and note evidence.",) if not has_audio else (),
        )
