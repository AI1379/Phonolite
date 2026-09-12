"""JSON serialization for ``music_core`` dataclasses (design doc section 8.4).

The Domain API returns everything inside the unified envelope, whose
``result`` must be JSON-safe (plain dicts/lists/primals). ``music_core`` types
are dataclasses that are not Pydantic models, so this module is the single
place that converts them to JSONable mappings. Keeping it centralised means
the routes never hand a raw dataclass to FastAPI and every tool emits the
same shape, which the tests (and the future frontend) can rely on.
"""

from __future__ import annotations

from typing import Any, cast

import yaml

from memory_core import (
    ClaimState,
    LearningState,
    MemoryClaim,
    MemoryEvent,
    MemoryPolicy,
    Observation,
    OutcomeProjection,
    ProjectStateEntry,
    RecallPlan,
    RecallView,
)
from music_core.analysis import Evidence, Finding, Location
from music_core.diff import NoteChange, ScoreDiff
from music_core.ir import (
    MeterEvent,
    NoteEvent,
    Region,
    ScoreDocument,
    TempoEvent,
)
from music_core.project import Decision, ProjectConfig, dumps_project
from music_core.transform import TransformResult
from music_core.validation import ValidationReport


def region_to_dict(region: Region | None) -> dict[str, object] | None:
    """A region as JSON, or ``None`` (so callers can echo "no region")."""
    if region is None:
        return None
    out: dict[str, object] = {
        "start_beat": region.start_beat,
        "end_beat": region.end_beat,
    }
    if region.track_ids is not None:
        out["track_ids"] = list(region.track_ids)
    if region.voice_ids is not None:
        out["voice_ids"] = list(region.voice_ids)
    return out


def note_to_dict(note: NoteEvent) -> dict[str, object]:
    """Full JSON view of a note, including the computed offset."""
    out: dict[str, object] = {
        "id": note.id,
        "track_id": note.track_id,
        "pitch": note.pitch,
        "onset_beats": note.onset_beats,
        "duration_beats": note.duration_beats,
        "offset_beats": note.offset_beats,
        "velocity": note.velocity,
    }
    if note.voice_id is not None:
        out["voice_id"] = note.voice_id
    if note.channel is not None:
        out["channel"] = note.channel
    if note.articulations:
        out["articulations"] = list(note.articulations)
    if note.source_ref is not None:
        out["source_ref"] = note.source_ref
    out["role"] = note.role
    out["transcription_status"] = note.transcription_status
    if note.reference_evidence is not None:
        evidence = note.reference_evidence
        out["reference_evidence"] = {"asset_id": evidence.asset_id, "start_seconds": evidence.start_seconds,
                                     "end_seconds": evidence.end_seconds, "method": evidence.method}
    return out


def _meter_to_dict(meter: MeterEvent) -> dict[str, object]:
    return {"beat": meter.beat, "numerator": meter.numerator, "denominator": meter.denominator}


def _tempo_to_dict(tempo: TempoEvent) -> dict[str, object]:
    return {"beat": tempo.beat, "bpm": tempo.bpm}


def score_summary_to_dict(doc: ScoreDocument) -> dict[str, object]:
    """Compact view for version lists; score_get separately pages actual notes."""
    track_ids = sorted({n.track_id for n in doc.notes})
    meta = doc.metadata
    out: dict[str, object] = {
        "version_id": doc.id,
        "ppq": doc.ppq,
        "duration_beats": doc.duration_beats,
        "note_count": len(doc.notes),
        "track_ids": track_ids,
        "meters": [_meter_to_dict(m) for m in doc.meters],
        "tempos": [_tempo_to_dict(t) for t in doc.tempos],
        "kind": doc.metadata.get("kind", "score"),
        "reference": ({"asset_id": doc.reference.asset_id,
                       "anchors": [{"seconds": item.seconds, "beat": item.beat} for item in doc.reference.anchors]}
                      if doc.reference is not None else None),
    }
    branch = meta.get("branch")
    if isinstance(branch, str):
        out["branch"] = branch
    parent = meta.get("parent_version")
    if isinstance(parent, str):
        out["parent_version"] = parent
    warnings = meta.get("import_warnings")
    if isinstance(warnings, list):
        out["import_warnings"] = list(warnings)
    return out


def location_to_dict(location: Location) -> dict[str, object]:
    out: dict[str, object] = {
        "start_beat": location.start_beat,
        "end_beat": location.end_beat,
        "track_ids": list(location.track_ids),
        "bars_label": location.render_bars(),
    }
    if location.bars is not None:
        out["bars"] = [location.bars[0], location.bars[1]]
    return out


def evidence_to_dict(evidence: Evidence) -> dict[str, object]:
    return {"metric": evidence.metric, "value": evidence.value}


def finding_to_dict(finding: Finding) -> dict[str, object]:
    return {
        "observation": finding.observation,
        "location": location_to_dict(finding.location),
        "evidence": [evidence_to_dict(e) for e in finding.evidence],
        "interpretation": finding.interpretation,
        "confidence": finding.confidence,
        "alternatives": list(finding.alternatives),
        "category": finding.category,
        "note_ids": list(finding.note_ids),
    }


def _field_changes_to_dict(
    changes: dict[str, tuple[Any, Any]],
) -> dict[str, list[object]]:
    """Tuples become 2-element JSON arrays: ``[before, after]``."""
    return {key: [old, new] for key, (old, new) in changes.items()}


def note_change_to_dict(change: NoteChange) -> dict[str, object]:
    out: dict[str, object] = {
        "note_id": change.note_id,
        "kind": change.kind,
        "field_changes": _field_changes_to_dict(change.field_changes),
    }
    out["before"] = note_to_dict(change.before) if change.before is not None else None
    out["after"] = note_to_dict(change.after) if change.after is not None else None
    return out


def diff_to_dict(diff_result: ScoreDiff) -> dict[str, object]:
    return {
        "is_empty": diff_result.is_empty,
        "summary": diff_result.summary,
        "added": [note_change_to_dict(c) for c in diff_result.added],
        "removed": [note_change_to_dict(c) for c in diff_result.removed],
        "modified": [note_change_to_dict(c) for c in diff_result.modified],
        "unchanged_count": diff_result.unchanged_count,
    }


def validation_to_dict(report: ValidationReport) -> dict[str, object]:
    return {
        "ok": report.ok,
        "errors": list(report.errors),
        "warnings": list(report.warnings),
    }


def transform_result_to_dict(result: TransformResult) -> dict[str, object]:
    """A transform outcome plus the new version's summary (see score_summary)."""
    return {
        "version": score_summary_to_dict(result.document),
        "branch": result.branch,
        "operation": result.operation,
        "description": result.description,
        "changed_event_ids": list(result.changed_event_ids),
        "validation": validation_to_dict(result.validation),
    }


def decision_to_dict(decision: Decision) -> dict[str, object]:
    out: dict[str, object] = {
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


def project_config_to_dict(config: ProjectConfig) -> dict[str, object]:
    """Round-trip the config through its own tested YAML serialiser.

    Reusing ``dumps_project`` guarantees the JSON view matches what
    ``project.yaml`` persistence produces, instead of a second hand-written
    projection that could drift from the schema.
    """
    data = yaml.safe_load(dumps_project(config))
    if not isinstance(data, dict):
        raise ValueError("project config did not serialise to a mapping")
    return cast(dict[str, object], data)


def memory_event_to_dict(event: MemoryEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "actor_id": event.actor_id,
        "project_id": event.project_id,
        "payload": event.payload,
        "occurred_at": event.occurred_at,
    }


def observation_to_dict(observation: Observation) -> dict[str, object]:
    return {
        "id": observation.id,
        "source_event_id": observation.source_event_id,
        "subject": observation.subject,
        "event": observation.event,
        "context": observation.context,
        "confidence": observation.confidence,
        "observed_at": observation.observed_at,
        "project_id": observation.project_id,
    }


def claim_to_dict(
    claim: MemoryClaim, state: ClaimState, policy: MemoryPolicy
) -> dict[str, object]:
    return {
        "claim": {
            "id": claim.id,
            "subject_type": claim.subject_type,
            "subject_id": claim.subject_id,
            "predicate": claim.predicate,
            "value": claim.value,
            "context_type": claim.context_type,
            "context_id": claim.context_id,
            "claim_type": claim.claim_type.value,
            "tags": list(claim.tags),
        },
        "state": {
            "status": state.status.value,
            "confidence": state.confidence,
            "valid_from": state.valid_from,
            "valid_until": state.valid_until,
            "superseded_by": state.superseded_by,
            "last_confirmed_at": state.last_confirmed_at,
        },
        "policy": {
            "owner_id": policy.owner_id,
            "visibility": policy.visibility,
            "sensitivity": policy.sensitivity.value,
            "allowed_contexts": list(policy.allowed_contexts),
        },
    }


def project_state_to_dict(state: ProjectStateEntry) -> dict[str, object]:
    return {
        "project_id": state.project_id,
        "key": state.key,
        "value": state.value,
        "source_event_id": state.source_event_id,
        "updated_at": state.updated_at,
    }


def learning_state_to_dict(state: LearningState) -> dict[str, object]:
    return {
        "subject_id": state.subject_id,
        "project_id": state.project_id,
        "focus": state.focus,
        "status": state.status,
        "mastery": state.mastery,
        "evidence_count": state.evidence_count,
        "source_event_id": state.source_event_id,
        "updated_at": state.updated_at,
    }


def recall_plan_to_dict(plan: RecallPlan) -> dict[str, object]:
    return {
        "channels": list(plan.channels),
        "entities": list(plan.entities),
        "time_horizon": plan.time_horizon,
        "need_raw_history": plan.need_raw_history,
        "channel_limits": dict(plan.channel_limits),
    }


def recall_view_to_dict(view: RecallView) -> dict[str, object]:
    return {
        "plan": recall_plan_to_dict(view.plan),
        "items": [
            {
                "channel": item.channel,
                "kind": item.kind,
                "id": item.id,
                "summary": item.summary,
                "confidence": item.confidence,
                "occurred_at": item.occurred_at,
                "data": item.data,
            }
            for item in view.items
        ],
    }


def outcome_projection_to_dict(projection: OutcomeProjection) -> dict[str, object]:
    return {
        "event": memory_event_to_dict(projection.event),
        "observation_id": projection.observation_id,
        "decision_claim_id": projection.decision_claim_id,
        "preference_claim_id": projection.preference_claim_id,
        "learning_focus": projection.learning_focus,
    }
