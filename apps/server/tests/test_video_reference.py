"""Real video decode, timestamp alignment, compatibility and persistence checks."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from workbench_server.assets import ReferenceRecord
from workbench_server.store import configure_project_store, get_store
from workbench_server.video import _executable, prepare_video


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("real video tests require FFmpeg/ffprobe")
    path = tmp_path / "reference.mp4"
    subprocess.run([_executable("ffmpeg"), "-nostdin", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x160:rate=20:duration=4",
                    "-itsoffset", "1", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=22050:duration=1",
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True, capture_output=True, timeout=30)
    return path


def test_video_waveform_keeps_delayed_audio_and_silent_tail(video_file: Path) -> None:
    data = video_file.read_bytes()
    result = prepare_video(data, "演奏.mp4")
    assert result.media_kind == "video"
    assert result.video_width == 320 and result.video_height == 160
    assert result.original == data
    assert result.video is not None and result.playback is not None
    assert result.has_audio
    assert result.duration_seconds == pytest.approx(4, abs=0.08)
    samples, sample_rate = sf.read(BytesIO(result.playback))
    assert len(samples) / sample_rate == pytest.approx(result.duration_seconds, abs=0.05)
    assert np.max(np.abs(samples[:int(0.7 * sample_rate)])) < 0.001
    assert np.sqrt(np.mean(samples[int(1.2 * sample_rate):int(1.7 * sample_rate)] ** 2)) > 0.02
    assert np.max(np.abs(samples[int(2.8 * sample_rate):])) < 0.001


def test_silent_video_remains_usable_for_visual_alignment(video_file: Path, tmp_path: Path) -> None:
    path = tmp_path / "silent.mp4"
    subprocess.run([_executable("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", str(video_file),
                    "-an", "-c:v", "copy", str(path)], check=True, capture_output=True, timeout=30)
    result = prepare_video(path.read_bytes(), "silent.mp4")
    assert result.video is not None
    assert not result.has_audio
    assert result.playback is None and result.peaks == []
    assert result.warnings


def test_video_reference_ranges_alignment_and_recovery(client: TestClient, video_file: Path) -> None:
    data = video_file.read_bytes()
    imported = client.post("/api/references/import-video", json={"filename": "演奏.mp4", "video_b64": base64.b64encode(data).decode()})
    assert imported.status_code == 200, imported.text
    reference = imported.json()["result"]["reference"]
    assert reference["media_kind"] == "video"
    original = client.get("/api/artifact/" + reference["original_token"])
    assert original.content == data
    video_url = "/api/artifact/" + reference["video_token"]
    preview = client.get(video_url)
    assert preview.headers["content-type"] == "video/mp4"
    partial = client.get(video_url, headers={"Range": "bytes=0-63"})
    assert partial.status_code == 206
    assert partial.content == preview.content[:64]
    anchors = [{"seconds": 1, "beat": 0}, {"seconds": 3, "beat": 4}]
    assert client.put(f"/api/references/{reference['id']}/alignment", json={"anchors": anchors}).status_code == 200
    draft = client.post("/api/score/draft", json={"reference_id": reference["id"]})
    assert draft.status_code == 200, draft.text
    assert draft.json()["result"]["version"]["reference"]["asset_id"] == reference["id"]
    configure_project_store(get_store().path)
    restored = client.get("/api/references").json()["result"]["references"][0]
    assert restored["video_token"] == reference["video_token"]
    assert restored["anchors"] == anchors
    assert client.get(video_url).content == preview.content
    assert client.get("/api/artifact/" + reference["original_token"]).content == data


def test_missing_video_decoder_returns_error_without_losing_audio_support(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("workbench_server.video.shutil.which", lambda _name: None)
    response = client.post("/api/references/import-video", json={"filename": "video.mp4", "video_b64": "YWJj"})
    assert response.status_code == 422
    assert "ffmpeg" in response.json()["result"]["error"]
    assert client.get("/api/references").json()["result"]["references"] == []


def test_legacy_audio_records_get_compatible_media_defaults() -> None:
    record = TypeAdapter(ReferenceRecord).validate_python({
        "id": "old", "filename": "source.wav", "sha256": "hash", "duration_seconds": 3,
        "sample_rate": 8000, "channels": 1, "original_token": "original", "playback_token": "audio",
        "peaks": [[-0.2, 0.2]], "anchors": [],
    })
    assert record.media_kind == "audio" and record.has_audio
    assert record.video_token is None


def test_invalid_video_does_not_commit_any_reference(client: TestClient) -> None:
    response = client.post("/api/references/import-video", json={"filename": "bad.mp4", "video_b64": "YWJj"})
    assert response.status_code == 422
    assert client.get("/api/references").json()["result"]["references"] == []


@pytest.mark.parametrize("container", ["mov", "mkv", "webm"])
def test_supported_video_containers(video_file: Path, tmp_path: Path, container: str) -> None:
    path = tmp_path / f"reference.{container}"
    codecs = ["-c:v", "libvpx-vp9", "-crf", "40", "-b:v", "0", "-c:a", "libopus"] if container == "webm" else ["-c", "copy"]
    subprocess.run([_executable("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", str(video_file),
                    *codecs, str(path)], check=True, capture_output=True, timeout=30)
    result = prepare_video(path.read_bytes(), path.name)
    assert result.video is not None and result.has_audio
    assert result.duration_seconds == pytest.approx(4, abs=0.15)
