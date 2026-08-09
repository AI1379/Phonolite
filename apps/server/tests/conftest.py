"""Shared pytest fixtures for the Workbench server tests."""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from music_core.ir import MeterEvent, NoteEvent, ScoreDocument
from music_core.io.midi import dumps_midi

from workbench_server.main import app
from workbench_server.memory import configure_memory_store
from workbench_server.store import get_store


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """A test client backed by isolated project and persistent-memory stores."""
    get_store().reset()
    configure_memory_store(tmp_path / "project.db")
    with TestClient(app) as test_client:
        yield test_client


def _build_piano_doc(bars: int, doc_id: str = "v") -> ScoreDocument:
    """A static piano texture: a low bass note plus a two-note chord per bar.

    The bass is always the lowest sounding note, so the transform's
    bass detector reliably finds it; the chord extremes never move, so the
    register/bass analyses flag a static, repetitive feeling (exactly what
    the vertical slice's "does this feel static?" step needs).
    """
    notes: list[NoteEvent] = []
    for bar in range(bars):
        start = bar * 4.0
        notes.append(
            NoteEvent(
                id=f"bass-{bar}", track_id="bass", pitch=36,
                onset_beats=start, duration_beats=4.0, velocity=80,
            )
        )
        notes.append(
            NoteEvent(
                id=f"mel-{bar}-a", track_id="piano", pitch=60,
                onset_beats=start, duration_beats=4.0, velocity=80,
            )
        )
        notes.append(
            NoteEvent(
                id=f"mel-{bar}-b", track_id="piano", pitch=64,
                onset_beats=start, duration_beats=4.0, velocity=80,
            )
        )
    return ScoreDocument(
        id=doc_id,
        ppq=480,
        notes=notes,
        meters=[MeterEvent(beat=0.0, numerator=4, denominator=4)],
    )


@pytest.fixture
def make_piano_b64() -> Callable[..., str]:
    """Factory: build a static piano score and return it as base64 MIDI."""

    def _build(*, bars: int = 4) -> str:
        doc = _build_piano_doc(bars=bars)
        return base64.b64encode(dumps_midi(doc)).decode("ascii")

    return _build


@pytest.fixture
def imported_main(client: TestClient, make_piano_b64: Callable[..., str]) -> str:
    """Import a 4-bar piano score and return its version id."""
    resp = client.post("/api/score/import", json={"midi_b64": make_piano_b64(bars=4)})
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]["version"]["version_id"]
