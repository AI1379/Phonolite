"""Audio render backends for the Score IR (design doc issue #8).

Renders a :class:`~music_core.ir.ScoreDocument` to an audio file via an
external synth. Two real backends are supported, both invoked through their
command-line interface so no Python binding has to ship with the package:

  - **FluidSynth** (``fluidsynth`` CLI + a SoundFont), the preferred path;
  - **MuseScore** (``musescore`` / ``mscore`` CLI).

Neither is required at install time: backends report availability via
:meth:`AudioBackend.is_available`, and ``render_score(..., backend="auto")``
picks the first available one. If no audio synth is present we fall back to
writing the prepared MIDI to disk and emit a warning — this keeps the
vertical slice end-to-end runnable anywhere while being explicit that the
result is not yet audio. Tests inject a stub backend, so no real synth is
needed for coverage.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from music_core.ir import ScoreDocument
from music_core.io.midi import dumps_midi


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
    proc = subprocess.run(cmd, capture_output=True, check=False)
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
    """Always-available fallback: write the prepared MIDI to disk.

    Not audio — ``render_score`` only selects this when no synth is present,
    and always warns about it. Useful so the slice stays runnable in minimal
    environments and for deterministic tests.
    """

    name: str = "midi-file"

    def is_available(self) -> bool:
        return True

    def render(
        self, *, midi_bytes: bytes, out_path: Path, sample_rate: int
    ) -> list[str]:
        midi_path = out_path.with_suffix(".mid")
        midi_path.write_bytes(midi_bytes)
        return [
            "No audio synth found; wrote MIDI instead of audio. "
            "Install FluidSynth + a SoundFont for audio output."
        ]


def _resolve_backends(
    backend: str | AudioBackend, soundfont: str | None
) -> tuple[list[AudioBackend], bool]:
    """Turn the ``backend`` argument into an ordered list of backends.

    Returns ``(backends, is_auto)``. When ``is_auto`` and the caller did not
    force a single named backend, audio backends are tried first and the MIDI
    fallback is appended last as a guarantee.
    """
    if not isinstance(backend, str):
        return [backend], False
    if backend == "fluidsynth":
        return [FluidSynthBackend(soundfont=soundfont)], False
    if backend == "musescore":
        return [MuseScoreBackend()], False
    if backend == "midi":
        return [MidiFileBackend()], False
    if backend == "auto":
        return [FluidSynthBackend(soundfont=soundfont), MuseScoreBackend(), MidiFileBackend()], True
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

    With ``backend="auto"`` (default), the first *available* backend wins:
    FluidSynth, then MuseScore, then the always-on MIDI fallback. Passing an
    :class:`AudioBackend` instance (e.g. a test stub) uses it directly.
    """
    midi_bytes = dumps_midi(doc)
    candidates, is_auto = _resolve_backends(backend, soundfont)
    target = Path(out_path)
    # Ensure the output directory exists so CLI backends and the MIDI fallback
    # never fail on a missing parent.
    target.parent.mkdir(parents=True, exist_ok=True)

    if is_auto:
        chosen = next((b for b in candidates if b.is_available()), None)
        if chosen is None:
            raise RenderError("No available render backend (tried fluidsynth, musescore).")
    else:
        chosen = candidates[0]
        if not chosen.is_available():
            raise RenderError(
                f"Requested backend {chosen.name!r} is not available in this environment."
            )

    warnings = chosen.render(midi_bytes=midi_bytes, out_path=target, sample_rate=sample_rate)
    actual_path = target
    if isinstance(chosen, MidiFileBackend):
        actual_path = target.with_suffix(".mid")
    return RenderResult(
        path=str(actual_path), backend=chosen.name, warnings=warnings
    )
