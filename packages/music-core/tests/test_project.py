"""Tests for project.yaml schema, loader, and decisions (design doc issue #3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from music_core.project import (
    ProjectSchemaError,
    dump_project,
    dumps_project,
    load_project,
    loads_project,
    record_decision,
    set_active_version,
)

# Mirrors design doc section 10.2, plus a decisions block.
SAMPLE_YAML = """\
id: lake-tower
title: Lake Tower
active_version: v013

current_goal:
  description: Write an eight-bar destabilising-but-not-breaking piano passage
  region:
    bars: [17, 24]

musical_context:
  meter: '9/8'
  tempo_bpm: 72
  tonal_center: d_minor

preserve:
  - main motive rising minor second
avoid:
  - cinematic major-chord stacking
learning_focus:
  - motif_development

decisions:
  - id: decision_abc
    at: '2025-01-01T00:00:00+00:00'
    summary: Chose the late-bass variant
    chosen_version_id: v013
    reason: The delayed resolution keeps tension
    tags: [bass, timing]

unknown_future_field: { keep: me }
"""


def test_load_then_dump_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "project.yaml"
    path.write_text(SAMPLE_YAML, encoding="utf-8")

    config = load_project(path)
    assert config.id == "lake-tower"
    assert config.title == "Lake Tower"
    assert config.active_version == "v013"
    assert config.current_goal is not None
    assert config.current_goal.region is not None
    assert config.current_goal.region.bars == (17, 24)
    assert config.musical_context is not None
    assert config.musical_context.tempo_bpm == 72.0
    assert config.musical_context.tonal_center == "d_minor"
    assert config.preserve == ("main motive rising minor second",)
    assert len(config.decisions) == 1
    assert config.decisions[0].tags == ("bass", "timing")
    # Unknown keys are preserved verbatim, not dropped.
    assert "unknown_future_field" in config.extra

    # Round-trip: dumping and reloading yields the same data.
    path.write_text(dumps_project(config), encoding="utf-8")
    reloaded = load_project(path)
    assert reloaded == config


def test_unknown_top_level_keys_survive_round_trip() -> None:
    config = loads_project(SAMPLE_YAML)
    dumped = dumps_project(config)
    assert "unknown_future_field" in dumped
    assert "keep: me" in dumped


def test_schema_error_on_missing_id() -> None:
    with pytest.raises(ProjectSchemaError):
        loads_project("title: No ID\n")
    with pytest.raises(ProjectSchemaError):
        loads_project("id: []\ntitle: bad\n")


def test_schema_error_on_wrong_types() -> None:
    with pytest.raises(ProjectSchemaError):
        loads_project("id: x\ntitle: 123\n")  # title not a string
    with pytest.raises(ProjectSchemaError):
        loads_project("id: x\ntitle: t\nmusical_context: []\n")


def test_empty_file_errors() -> None:
    with pytest.raises(ProjectSchemaError):
        loads_project("")


def test_record_decision_appends_immutably() -> None:
    config = loads_project("id: p\ntitle: P\n")
    assert config.decisions == ()

    new_config, decision = record_decision(
        config,
        summary="Accepted variant B",
        chosen_version_id="v014",
        reason="Better bass motion",
        tags=("bass",),
    )
    # Original config untouched (immutable).
    assert config.decisions == ()
    assert new_config.decisions == (decision,)
    assert decision.id.startswith("decision_")
    assert decision.summary == "Accepted variant B"
    assert decision.chosen_version_id == "v014"
    assert decision.at  # ISO timestamp generated


def test_record_decision_round_trips_through_yaml() -> None:
    config = loads_project("id: p\ntitle: P\n")
    new_config, decision = record_decision(config, summary="Pick A")
    text = dumps_project(new_config)
    assert "decisions:" in text
    assert "Pick A" in text
    reloaded = loads_project(text)
    assert reloaded.decisions[0].summary == "Pick A"
    assert reloaded.decisions[0].id == decision.id


def test_set_active_version_returns_new_config() -> None:
    config = loads_project("id: p\ntitle: P\nactive_version: v1\n")
    updated = set_active_version(config, "v2")
    assert config.active_version == "v1"  # unchanged
    assert updated.active_version == "v2"


def test_dump_project_writes_file(tmp_path: Path) -> None:
    config = loads_project("id: p\ntitle: P\n")
    out = tmp_path / "out.yaml"
    dump_project(config, out)
    assert out.read_text(encoding="utf-8").startswith("id: p")
