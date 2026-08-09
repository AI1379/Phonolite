"""Workbench server entry point.

Serves the Domain API (``/api/*``) and the event WebSocket (``/ws``) that
the Music Workbench UI (and later DAW bridges / agent runtimes) talk to.

The HTTP layer is intentionally thin (design doc section 3.1): each route
only validates its request, calls into ``music_core``, and wraps the result
in the section-8.4 envelope. No musical reasoning lives here.

Run with::

    uv run workbench-server        # 127.0.0.1:8000, auto-reload
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from music_core.analysis import inspect
from music_core.diff import diff
from music_core.io.midi import dumps_midi, loads_midi
from music_core.ir import Region
from music_core.render import RenderError, render_score
from music_core.transform import TransformRequest, apply_transform

from workbench_server import __version__
from workbench_server.envelope import envelope
from workbench_server.schemas import (
    AcceptRequest,
    ChooseRequest,
    CompareRequest,
    DecisionRequest,
    GoalUpdateRequest,
    ImportRequest,
    TransformRequestModel,
)
from workbench_server.serialization import (
    decision_to_dict,
    diff_to_dict,
    finding_to_dict,
    project_config_to_dict,
    transform_result_to_dict,
)
from workbench_server.store import (
    ArtifactNotFound,
    VersionNotFound,
    decode_midi_b64,
    get_store,
)

app = FastAPI(title="Music Agent Workbench", version=__version__)


# --------------------------------------------------------------------------- #
# Error envelope helper + exception handlers
# --------------------------------------------------------------------------- #

def _error_envelope(message: str, *, tool: str = "error") -> dict[str, Any]:
    """Build a section-8.4 envelope signalling failure."""
    return envelope(
        {"error": message},
        tool=tool,
        ok=False,
        warnings=[message],
        version=__version__,
    )


@app.exception_handler(VersionNotFound)
async def _version_not_found_handler(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
    _request: Request, exc: VersionNotFound
) -> JSONResponse:
    return JSONResponse(status_code=404, content=_error_envelope(str(exc)))


@app.exception_handler(ArtifactNotFound)
async def _artifact_not_found_handler(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
    _request: Request, exc: ArtifactNotFound
) -> JSONResponse:
    return JSONResponse(status_code=404, content=_error_envelope(str(exc)))


@app.exception_handler(ValueError)
async def _value_error_handler(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
    _request: Request, exc: ValueError
) -> JSONResponse:
    # music_core raises ValueError for bad request parameters (unknown
    # operation, non-positive factor, bad base64, schema mismatches, ...).
    return JSONResponse(status_code=422, content=_error_envelope(str(exc)))


@app.exception_handler(RenderError)
async def _render_error_handler(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
    _request: Request, exc: RenderError
) -> JSONResponse:
    # A requested backend being unavailable is a client-fixable condition.
    return JSONResponse(status_code=422, content=_error_envelope(str(exc)))


# --------------------------------------------------------------------------- #
# Health + event channel
# --------------------------------------------------------------------------- #

@app.get("/api/health")
def health() -> dict[str, Any]:
    """Liveness probe; also proves the workspace wiring (music-core import)."""
    from music_core import __version__ as music_core_version

    return envelope(
        {
            "service": "workbench-server",
            "version": __version__,
            "music_core_version": music_core_version,
        },
        tool="health",
        version=__version__,
    )


@app.websocket("/ws")
async def events(websocket: WebSocket) -> None:
    """Event channel placeholder: greets, then echoes until disconnect.

    Later this streams agent/runtime events (design doc section 6.2).
    """
    await websocket.accept()
    await websocket.send_json(
        {"type": "hello", "payload": {"service": "workbench-server", "version": __version__}}
    )
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_json({"type": "echo", "payload": message})
    except WebSocketDisconnect:
        pass


# --------------------------------------------------------------------------- #
# Score tools (design doc section 8.2)
# --------------------------------------------------------------------------- #


def _default_branch(operation: str) -> str:
    if operation == "delay_bass_resolution":
        return "exp/delayed-bass"
    if operation == "rhythmic_scaling":
        return "exp/rhythmic-scaling"
    return f"exp/{operation}"


@app.post("/api/score/import")
def score_import(body: ImportRequest) -> dict[str, Any]:
    """Import a MIDI file as the project's main score version."""
    raw = decode_midi_b64(body.midi_b64)
    document = loads_midi(raw)
    store = get_store()
    store.ensure_project(project_id=body.project_id, title=body.title)
    version = store.add_version(
        document,
        parent_id=None,
        branch="main",
        origin="import",
        description="Imported MIDI",
    )
    # First import becomes the active (main) version explicitly.
    if store.active_version_id() is None:
        store.accept_variant(version.version_id)
    return envelope(
        {"version": version.to_dict()},
        tool="import_score",
        inputs=[version.version_id],
        version=__version__,
    )


@app.get("/api/score/{version_id}")
def score_get(version_id: str) -> dict[str, Any]:
    """Return a version's summary (no per-note listing; use export for that)."""
    version = get_store().get_version(version_id)
    return envelope(
        {"version": version.to_dict()},
        tool="get_score",
        inputs=[version_id],
        version=__version__,
    )


@app.get("/api/score/{version_id}/inspect")
def score_inspect(
    version_id: str,
    start_beat: float | None = Query(default=None),
    end_beat: float | None = Query(default=None),
    track_ids: str | None = Query(default=None),
) -> dict[str, Any]:
    """Run stage-1 analyses (register, density, bass contour) over a region."""
    document = get_store().get_version(version_id).document
    region: Region | None = None
    if start_beat is not None and end_beat is not None:
        tids = tuple(track_ids.split(",")) if track_ids else None
        region = Region(start_beat=start_beat, end_beat=end_beat, track_ids=tids)
    elif start_beat is not None or end_beat is not None:
        raise ValueError("inspect region requires both start_beat and end_beat")
    findings = inspect(document, region)
    return envelope(
        {
            "version_id": version_id,
            "region": _region_brief(region, document),
            "findings": [finding_to_dict(f) for f in findings],
        },
        tool="inspect_score",
        inputs=[version_id],
        version=__version__,
    )


@app.post("/api/score/compare")
def score_compare(body: CompareRequest) -> dict[str, Any]:
    """Compare two stored versions by stable note id."""
    store = get_store()
    before = store.get_version(body.before_version_id).document
    after = store.get_version(body.after_version_id).document
    result = diff(before, after)
    return envelope(
        diff_to_dict(result),
        tool="compare_versions",
        inputs=[body.before_version_id, body.after_version_id],
        version=__version__,
    )


@app.post("/api/score/transform")
def score_transform(body: TransformRequestModel) -> dict[str, Any]:
    """Apply a controlled transform, storing the new version on its branch."""
    store = get_store()
    source = store.get_version(body.source_version_id).document
    request = TransformRequest(
        source_version_id=body.source_version_id,
        region=body.region.to_region(),
        operation=body.operation,
        parameters=dict(body.parameters),
        preserve=list(body.preserve),
        vary=list(body.vary),
        output_branch=body.output_branch or _default_branch(body.operation),
    )
    result = apply_transform(source, request)
    version = store.add_version(
        result.document,
        parent_id=body.source_version_id,
        branch=result.branch,
        origin="transform",
        description=result.description,
    )
    return envelope(
        transform_result_to_dict(result),
        tool="apply_transformation",
        inputs=[body.source_version_id, version.version_id],
        artifacts=[version.version_id],
        version=__version__,
    )


@app.post("/api/score/{version_id}/render")
def score_render(
    version_id: str, backend: str = Query(default="auto")
) -> dict[str, Any]:
    """Render a version to audio (or MIDI fallback) and store it as an artifact."""
    document = get_store().get_version(version_id).document
    with tempfile.TemporaryDirectory(prefix="workbench-render-") as tmp:
        out_path = Path(tmp) / f"{version_id}.out"
        result = render_score(document, out_path, backend=backend)
        data = Path(result.path).read_bytes()
    is_midi = result.backend == "midi-file"
    store = get_store()
    artifact = store.store_artifact(
        content_type="audio/midi" if is_midi else "audio/wav",
        filename=f"{version_id}.{'mid' if is_midi else 'wav'}",
        data=data,
    )
    return envelope(
        {
            "backend": result.backend,
            "warnings": list(result.warnings),
            "artifact_token": artifact.token,
            "filename": artifact.filename,
            "size_bytes": len(data),
        },
        tool="render_score",
        inputs=[version_id],
        artifacts=[artifact.token],
        version=__version__,
    )


@app.post("/api/score/{version_id}/export")
def score_export(version_id: str) -> dict[str, Any]:
    """Export a version as Standard MIDI File bytes (an artifact token)."""
    document = get_store().get_version(version_id).document
    data = dumps_midi(document)
    artifact = get_store().store_artifact(
        content_type="audio/midi",
        filename=f"{version_id}.mid",
        data=data,
    )
    return envelope(
        {
            "filename": artifact.filename,
            "size_bytes": len(data),
            "artifact_token": artifact.token,
        },
        tool="export_score",
        inputs=[version_id],
        artifacts=[artifact.token],
        version=__version__,
    )


@app.get("/api/artifact/{token}")
def artifact_get(token: str) -> Response:
    """Download a previously produced artifact (render/export) by token."""
    record = get_store().get_artifact(token)
    return Response(
        content=record.data,
        media_type=record.content_type,
        headers={"Content-Disposition": f'attachment; filename="{record.filename}"'},
    )


# --------------------------------------------------------------------------- #
# Project tools (design doc section 8.1)
# --------------------------------------------------------------------------- #


def _versions_summary(versions: list[Any]) -> list[dict[str, object]]:
    # ``StoredVersion.to_dict`` returns the JSON view kept in ``store``; we
    # treat it opaquely here so this module does not import the dataclass.
    return [version.to_dict() for version in versions]


@app.get("/api/project")
def project_status() -> dict[str, Any]:
    """Return the project config, version tree, and active version."""
    store = get_store()
    config = store.config
    return envelope(
        {
            "project": project_config_to_dict(config),
            "active_version": store.active_version_id(),
            "versions": _versions_summary(store.list_versions()),
        },
        tool="project_status",
        version=__version__,
    )


@app.patch("/api/project/goal")
def project_update_goal(body: GoalUpdateRequest) -> dict[str, Any]:
    """Set the current goal (description + optional bar/beat region)."""
    config = get_store().update_goal(body.description, body.bars, body.beats)
    return envelope(
        {"project": project_config_to_dict(config)},
        tool="project_update_goal",
        version=__version__,
    )


@app.post("/api/project/decision")
def project_record_decision(body: DecisionRequest) -> dict[str, Any]:
    """Append an explicit, audit-log-style decision to the project config."""
    config, decision = get_store().record_decision(
        summary=body.summary,
        chosen_version_id=body.chosen_version_id,
        reason=body.reason,
        tags=tuple(body.tags),
    )
    return envelope(
        {"decision": decision_to_dict(decision), "project": project_config_to_dict(config)},
        tool="project_record_decision",
        version=__version__,
    )


@app.post("/api/project/accept")
def project_accept_variant(body: AcceptRequest) -> dict[str, Any]:
    """Promote a variant to the active version (never silent; explicit accept)."""
    config = get_store().accept_variant(body.version_id)
    return envelope(
        {"project": project_config_to_dict(config), "active_version": body.version_id},
        tool="project_accept_variant",
        inputs=[body.version_id],
        version=__version__,
    )


@app.post("/api/project/choose")
def project_choose(body: ChooseRequest) -> dict[str, Any]:
    """A/B selection: record a decision and accept the chosen variant.

    This is the slice's "A/B Selection + Project Decision" step in one call.
    The user-supplied ``reason`` is the lightweight learning event captured
    for MVP-1 (structured learning state arrives in MVP-2).
    """
    store = get_store()
    if not store.has_version(body.chosen_version_id):
        raise VersionNotFound(body.chosen_version_id)
    _, decision = store.record_decision(
        summary=f"Selected variant {body.chosen_version_id}",
        chosen_version_id=body.chosen_version_id,
        reason=body.reason,
        tags=tuple(body.tags),
    )
    config = store.accept_variant(body.chosen_version_id)
    return envelope(
        {"decision": decision_to_dict(decision), "project": project_config_to_dict(config)},
        tool="project_choose",
        inputs=[body.chosen_version_id],
        version=__version__,
    )


# --------------------------------------------------------------------------- #
# Small shared helpers
# --------------------------------------------------------------------------- #

def _region_brief(region: Region | None, document: Any) -> dict[str, object]:
    """A compact region description for the inspect result."""
    if region is None:
        end = document.duration_beats if document.notes else 0.0
        return {"start_beat": 0.0, "end_beat": end, "scope": "whole-score"}
    brief: dict[str, object] = {
        "start_beat": region.start_beat,
        "end_beat": region.end_beat,
        "scope": "region",
    }
    if region.track_ids is not None:
        brief["track_ids"] = list(region.track_ids)
    return brief


def run() -> None:
    """Console-script entry point (``uv run workbench-server``)."""
    uvicorn.run("workbench_server.main:app", host="127.0.0.1", port=8000, reload=True)
