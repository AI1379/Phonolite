"""Audio render backends for the Score IR (design doc issue #8).

Renders a :class:`~music_core.ir.ScoreDocument` to audio using optional
external synthesizers or the built-in reference-tone backend:

  - **FluidSynth** (``fluidsynth`` CLI + a SoundFont), the preferred path;
  - **MuseScore** (``musescore`` / ``mscore`` CLI);
  - **Preview** (numpy, tempo/velocity/sustain, fixed reference timbre).

Neither is required at install time: backends report availability via
:meth:`AudioBackend.is_available`, and ``render_score(..., backend="auto")``
tries available external backends, then produces an actual preview WAV even
without a synth installation. MIDI file output must be requested explicitly.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from music_core.ir import ScoreDocument
from music_core.io.midi import dumps_midi, loads_midi
from music_core.preview import render_preview


class RenderError(RuntimeError):
    """Raised when rendering fails or no usable backend is available."""


@dataclass(frozen=True)
class RenderResult:
    """Outcome of a render: where it landed, via which backend, with warnings."""

    path: str
    backend: str
    warnings: list[str]


@runtime_checkable
class AudioBackend(Protocol):
    """A render backend that turns MIDI bytes into an on-disk audio file."""

    name: str

    def is_available(self) -> bool:
        """True when this backend can run in the current environment."""
        ...

    def render(
        self, *, midi_bytes: bytes, out_path: Path, sample_rate: int
    ) -> list[str]:
        """Render ``midi_bytes`` to ``out_path``; return any warnings."""
        ...


def _which_any(names: tuple[str, ...]) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path is not None:
            return path
    return None


def _run(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise RenderError("Audio renderer timed out after 120 seconds") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace").strip()
        raise RenderError(
            f"{cmd[0]} exited {proc.returncode}: {stderr or 'no stderr captured'}"
        )
    return proc.stderr.decode(errors="replace").strip()


@dataclass
class FluidSynthBackend:
    """Render via the ``fluidsynth`` CLI and a SoundFont (.sf2/.sf3)."""

    soundfont: str | None = None
    name: str = "fluidsynth"

    def is_available(self) -> bool:
        if self.soundfont is None:
            return False
        if _which_any(("fluidsynth",)) is None:
            return False
        return Path(self.soundfont).is_file()

    def render(
        self, *, midi_bytes: bytes, out_path: Path, sample_rate: int
    ) -> list[str]:
        exe = _which_any(("fluidsynth",))
        sf = self.soundfont
        if exe is None:
            raise RenderError("fluidsynth executable not found on PATH")
        if sf is None or not Path(sf).is_file():
            raise RenderError(f"SoundFont not found: {sf!r}")
        with tempfile.TemporaryDirectory(prefix="workbench-render-") as tmp:
            mid_path = Path(tmp) / "render.mid"
            mid_path.write_bytes(midi_bytes)
            cmd = [
                exe, "-n", "-i", "-q",
                "-F", str(out_path),
                "-r", str(sample_rate),
                sf, str(mid_path),
            ]
            _run(cmd)
        return [f"Rendered with FluidSynth using {Path(sf).name}."]


@dataclass
class MuseScoreBackend:
    """Render via the ``musescore`` / ``mscore`` CLI."""

    name: str = "musescore"

    def is_available(self) -> bool:
        return _which_any(("musescore", "mscore3", "mscore")) is not None

    def render(
        self, *, midi_bytes: bytes, out_path: Path, sample_rate: int
    ) -> list[str]:
        exe = _which_any(("musescore", "mscore3", "mscore"))
        if exe is None:
            raise RenderError("musescore/mscore executable not found on PATH")
        with tempfile.TemporaryDirectory(prefix="workbench-render-") as tmp:
            mid_path = Path(tmp) / "render.mid"
            mid_path.write_bytes(midi_bytes)
            cmd = [exe, "-o", str(out_path), str(mid_path)]
            _run(cmd)
        return [f"Rendered with MuseScore ({Path(exe).name})."]


@dataclass
class MidiFileBackend:
    """Explicit file exchange backend; this output is MIDI, not audio."""

    name: str = "midi-file"

    def is_available(self) -> bool:
        return True

    def render(
        self, *, midi_bytes: bytes, out_path: Path, sample_rate: int
    ) -> list[str]:
        midi_path = out_path.with_suffix(".mid")
        midi_path.write_bytes(midi_bytes)
        return [
            "Explicit MIDI output; select preview or auto for playable WAV audio."
        ]


@dataclass
class PreviewBackend:
    """Always-available reference-tone audio backend."""

    name: str = "preview"

    def is_available(self) -> bool:
        return True

    def render(self, *, midi_bytes: bytes, out_path: Path, sample_rate: int) -> list[str]:
        return render_preview(loads_midi(midi_bytes), out_path, sample_rate)


def _resolve_backends(
    backend: str | AudioBackend, soundfont: str | None
) -> tuple[list[AudioBackend], bool]:
    """Turn the ``backend`` argument into an ordered list of backends.

    Returns ``(backends, is_auto)``. When ``is_auto`` and the caller did not
    force a single named backend, external backends precede built-in preview.
    """
    if not isinstance(backend, str):
        return [backend], False
    if backend == "fluidsynth":
        return [FluidSynthBackend(soundfont=soundfont)], False
    if backend == "musescore":
        return [MuseScoreBackend()], False
    if backend == "midi":
        return [MidiFileBackend()], False
    if backend == "preview":
        return [PreviewBackend()], False
    if backend == "auto":
        return [FluidSynthBackend(soundfont=soundfont), MuseScoreBackend(), PreviewBackend()], True
    raise ValueError(f"Unknown backend: {backend!r}")


def render_score(
    doc: ScoreDocument,
    out_path: str | Path,
    *,
    backend: str | AudioBackend = "auto",
    soundfont: str | None = None,
    sample_rate: int = 44100,
) -> RenderResult:
    """Render ``doc`` to ``out_path`` using the selected backend.

    With ``backend="auto"`` (default), try FluidSynth, MuseScore, then preview.
    Explicit backends surface failures; auto retains failure warnings while
    trying its next candidate. An injected backend is used directly.
    """
    midi_bytes = dumps_midi(doc)
    candidates, is_auto = _resolve_backends(backend, soundfont)
    target = Path(out_path)
    # Ensure the output directory exists so CLI backends and the MIDI fallback
    # never fail on a missing parent.
    target.parent.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    for chosen in candidates:
        if not chosen.is_available():
            if is_auto:
                continue
            raise RenderError(f"Requested backend {chosen.name!r} is not available in this environment.")
        actual_path = target.with_suffix(".mid") if isinstance(chosen, MidiFileBackend) else target
        try:
            warnings = chosen.render(midi_bytes=midi_bytes, out_path=target, sample_rate=sample_rate)
            if not actual_path.is_file() or actual_path.stat().st_size == 0:
                raise RenderError(f"{chosen.name} produced no output")
        except (RenderError, OSError) as exc:
            if not is_auto:
                raise RenderError(str(exc)) from exc
            failures.append(f"{chosen.name} failed: {exc}")
            continue
        return RenderResult(path=str(actual_path), backend=chosen.name, warnings=[*failures, *warnings])
    raise RenderError("No usable audio renderer: " + "; ".join(failures))
