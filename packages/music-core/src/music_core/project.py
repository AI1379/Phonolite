"""``project.yaml`` schema, loader, and decision recording (design doc issue #3).

The project file is the explicit anchor for the vertical slice's
"Project Goal" and "Project Decision" steps. Keeping it as structured YAML
(rather than something the LLM summarises from chat history) enforces the
design red line: business state is explicit data, not derived from prose.

The schema mirrors design doc section 10.2. Unknown top-level keys are
preserved verbatim (in ``ProjectConfig.extra``) so a newer Workbench never
silently drops fields an older one wrote. Loading is strict about the types
it *does* understand and raises :class:`ProjectSchemaError` with a clear
message on mismatch, instead of coercing silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import yaml

from music_core.ir import MetadataValue, new_event_id


class ProjectSchemaError(ValueError):
    """Raised when ``project.yaml`` cannot be interpreted as the schema."""


@dataclass(frozen=True)
class GoalRegion:
    """The region a goal refers to, by bars and/or beats."""

    bars: tuple[int, int] | None = None
    beats: tuple[float, float] | None = None


@dataclass(frozen=True)
class ProjectGoal:
    """The current, user-stated goal for the active region."""

    description: str
    region: GoalRegion | None = None


@dataclass(frozen=True)
class MusicalContext:
    """Stable musical frame: meter string, tempo, tonal centre."""

    meter: str | None = None
    tempo_bpm: float | None = None
    tonal_center: str | None = None


@dataclass(frozen=True)
class Decision:
    """An explicit, recorded project decision (``project_record_decision``)."""

    id: str
    at: str  # ISO-8601 UTC timestamp
    summary: str
    chosen_version_id: str | None = None
    reason: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectConfig:
    """In-memory representation of ``project.yaml``."""

    id: str
    title: str
    active_version: str | None = None
    current_goal: ProjectGoal | None = None
    musical_context: MusicalContext | None = None
    preserve: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    learning_focus: tuple[str, ...] = ()
    decisions: tuple[Decision, ...] = ()
    extra: dict[str, MetadataValue] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Parsing: YAML -> dataclasses
# --------------------------------------------------------------------------- #

_KNOWN_TOP_KEYS = {
    "id",
    "title",
    "active_version",
    "current_goal",
    "musical_context",
    "preserve",
    "avoid",
    "learning_focus",
    "decisions",
}


def _as_mapping(node: object, *, where: str) -> dict[str, Any]:
    if not isinstance(node, dict):
        raise ProjectSchemaError(f"{where}: expected a mapping, got {type(node).__name__}")
    return cast(dict[str, Any], node)


def _require_str(node: dict[str, Any], key: str, *, where: str) -> str:
    if key not in node:
        raise ProjectSchemaError(f"{where}: missing required field {key!r}")
    value = node[key]
    if not isinstance(value, str):
        raise ProjectSchemaError(f"{where}: {key!r} must be a string, got {type(value).__name__}")
    return value


def _optional_str(node: dict[str, Any], key: str) -> str | None:
    value = node.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProjectSchemaError(f"field {key!r} must be a string, got {type(value).__name__}")
    return value


def _optional_number(node: dict[str, Any], key: str) -> float | None:
    value = node.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProjectSchemaError(f"field {key!r} must be a number, got {type(value).__name__}")
    return float(value)


def _optional_str_list(node: dict[str, Any], key: str) -> tuple[str, ...]:
    value = node.get(key)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ProjectSchemaError(f"field {key!r} must be a list, got {type(value).__name__}")
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise ProjectSchemaError(
                f"field {key!r}[{i}] must be a string, got {type(item).__name__}"
            )
        out.append(item)
    return tuple(out)


def _parse_goal_region(node: object) -> GoalRegion | None:
    if node is None:
        return None
    region = _as_mapping(node, where="current_goal.region")
    bars_raw = region.get("bars")
    beats_raw = region.get("beats")
    bars = _parse_int_pair(bars_raw, "current_goal.region.bars") if bars_raw is not None else None
    beats = (
        _parse_float_pair(beats_raw, "current_goal.region.beats") if beats_raw is not None else None
    )
    return GoalRegion(bars=bars, beats=beats)


def _parse_int_pair(value: object, where: str) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise ProjectSchemaError(f"{where}: expected a 2-element list, got {value!r}")
    a, b = value
    if not isinstance(a, int) or isinstance(a, bool) or not isinstance(b, int) or isinstance(b, bool):
        raise ProjectSchemaError(f"{where}: both elements must be integers, got {value!r}")
    return a, b


def _parse_float_pair(value: object, where: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ProjectSchemaError(f"{where}: expected a 2-element list, got {value!r}")
    a, b = value
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ProjectSchemaError(f"{where}: both elements must be numbers, got {value!r}")
    return float(a), float(b)


def _parse_goal(node: object) -> ProjectGoal | None:
    if node is None:
        return None
    goal = _as_mapping(node, where="current_goal")
    description = _require_str(goal, "description", where="current_goal")
    region = _parse_goal_region(goal.get("region"))
    return ProjectGoal(description=description, region=region)


def _parse_context(node: object) -> MusicalContext | None:
    if node is None:
        return None
    ctx = _as_mapping(node, where="musical_context")
    return MusicalContext(
        meter=_optional_str(ctx, "meter"),
        tempo_bpm=_optional_number(ctx, "tempo_bpm"),
        tonal_center=_optional_str(ctx, "tonal_center"),
    )


def _parse_decisions(node: object) -> tuple[Decision, ...]:
    if node is None:
        return ()
    if not isinstance(node, list):
        raise ProjectSchemaError("'decisions' must be a list")
    out: list[Decision] = []
    for i, item in enumerate(node):
        d = _as_mapping(item, where=f"decisions[{i}]")
        out.append(
            Decision(
                id=_require_str(d, "id", where=f"decisions[{i}]"),
                at=_require_str(d, "at", where=f"decisions[{i}]"),
                summary=_require_str(d, "summary", where=f"decisions[{i}]"),
                chosen_version_id=_optional_str(d, "chosen_version_id"),
                reason=_optional_str(d, "reason"),
                tags=_optional_str_list(d, "tags"),
            )
        )
    return tuple(out)


def _config_from_dict(data: object) -> ProjectConfig:
    root = _as_mapping(data, where="project.yaml root")
    project_id = _require_str(root, "id", where="project.yaml root")
    title = _require_str(root, "title", where="project.yaml root")
    extra = {
        key: cast(MetadataValue, value)
        for key, value in root.items()
        if key not in _KNOWN_TOP_KEYS
    }
    return ProjectConfig(
        id=project_id,
        title=title,
        active_version=_optional_str(root, "active_version"),
        current_goal=_parse_goal(root.get("current_goal")),
        musical_context=_parse_context(root.get("musical_context")),
        preserve=_optional_str_list(root, "preserve"),
        avoid=_optional_str_list(root, "avoid"),
        learning_focus=_optional_str_list(root, "learning_focus"),
        decisions=_parse_decisions(root.get("decisions")),
        extra=extra,
    )


def loads_project(text: str) -> ProjectConfig:
    """Parse ``project.yaml`` text into a :class:`ProjectConfig`."""
    data = yaml.safe_load(text)
    if data is None:
        raise ProjectSchemaError("project.yaml is empty")
    return _config_from_dict(data)


def load_project(path: str | Path) -> ProjectConfig:
    """Load a :class:`ProjectConfig` from ``path``."""
    return loads_project(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Dumping: dataclasses -> YAML
# --------------------------------------------------------------------------- #

def _goal_region_to_dict(region: GoalRegion | None) -> dict[str, Any] | None:
    if region is None:
        return None
    out: dict[str, Any] = {}
    if region.bars is not None:
        out["bars"] = list(region.bars)
    if region.beats is not None:
        out["beats"] = list(region.beats)
    return out or None


def _goal_to_dict(goal: ProjectGoal | None) -> dict[str, Any] | None:
    if goal is None:
        return None
    out: dict[str, Any] = {"description": goal.description}
    region = _goal_region_to_dict(goal.region)
    if region is not None:
        out["region"] = region
    return out


def _context_to_dict(ctx: MusicalContext | None) -> dict[str, Any] | None:
    if ctx is None:
        return None
    out: dict[str, Any] = {}
    if ctx.meter is not None:
        out["meter"] = ctx.meter
    if ctx.tempo_bpm is not None:
        out["tempo_bpm"] = ctx.tempo_bpm
    if ctx.tonal_center is not None:
        out["tonal_center"] = ctx.tonal_center
    return out or None


def _decision_to_dict(decision: Decision) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": decision.id,
        "at": decision.at,
        "summary": decision.summary,
    }
    if decision.chosen_version_id is not None:
        out["chosen_version_id"] = decision.chosen_version_id
    if decision.reason is not None:
        out["reason"] = decision.reason
    if decision.tags:
        out["tags"] = list(decision.tags)
    return out


def _config_to_dict(config: ProjectConfig) -> dict[str, Any]:
    out: dict[str, Any] = {"id": config.id, "title": config.title}
    if config.active_version is not None:
        out["active_version"] = config.active_version
    goal = _goal_to_dict(config.current_goal)
    if goal is not None:
        out["current_goal"] = goal
    ctx = _context_to_dict(config.musical_context)
    if ctx is not None:
        out["musical_context"] = ctx
    if config.preserve:
        out["preserve"] = list(config.preserve)
    if config.avoid:
        out["avoid"] = list(config.avoid)
    if config.learning_focus:
        out["learning_focus"] = list(config.learning_focus)
    if config.decisions:
        out["decisions"] = [_decision_to_dict(d) for d in config.decisions]
    # Round-trip unknown keys verbatim so newer/older versions lose no data.
    for key, value in config.extra.items():
        out.setdefault(key, value)
    return out


def dumps_project(config: ProjectConfig) -> str:
    """Serialize a :class:`ProjectConfig` to ``project.yaml`` text."""
    return yaml.safe_dump(
        _config_to_dict(config), sort_keys=False, allow_unicode=True, default_flow_style=False
    )


def dump_project(config: ProjectConfig, path: str | Path) -> None:
    """Write a :class:`ProjectConfig` to ``path`` as ``project.yaml``."""
    Path(path).write_text(dumps_project(config), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Mutations (return new immutable configs)
# --------------------------------------------------------------------------- #

def record_decision(
    config: ProjectConfig,
    *,
    summary: str,
    chosen_version_id: str | None = None,
    reason: str | None = None,
    tags: tuple[str, ...] = (),
    at: str | None = None,
) -> tuple[ProjectConfig, Decision]:
    """Append a :class:`Decision`, returning a new config and the decision.

    The config is immutable, so this returns a copy with the decision added;
    the caller writes it back with :func:`dump_project`. ``at`` defaults to
    the current UTC time in ISO-8601 so decisions form an ordered audit log.
    """
    timestamp = at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    decision = Decision(
        id=new_event_id("decision"),
        at=timestamp,
        summary=summary,
        chosen_version_id=chosen_version_id,
        reason=reason,
        tags=tags,
    )
    new_config = replace(config, decisions=(*config.decisions, decision))
    return new_config, decision


def set_active_version(config: ProjectConfig, version_id: str) -> ProjectConfig:
    """Return a new config with ``active_version`` updated.

    Used by the "project_accept_variant" step: accepting a variant promotes
    it to the active version explicitly, never silently.
    """
    return replace(config, active_version=version_id)
