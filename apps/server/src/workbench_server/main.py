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

import asyncio
import os
import re
from urllib.parse import quote
import tempfile
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import RequestResponseEndpoint
from memory_core import ExperimentOutcome, RecallPlanner, recall
from music_core.analysis import inspect
from music_core.diff import diff
from music_core.io.midi import dumps_midi, loads_midi
from music_core.ir import Region, ScoreDocument
from music_core.render import RenderError, render_score
from music_core.transform import TransformRequest, apply_transform

from workbench_server import __version__
from workbench_server.agent import (
    AgentTaskEvent,
    AgentTaskNotFound,
    get_agent_manager,
    shutdown_agent_manager,
)
from workbench_server.envelope import envelope
from workbench_server.memory import MemoryRecordNotFound, get_memory_store
from workbench_server.schemas import (
    AcceptRequest,
    AgentResumeRequest,
    AgentTaskRequest,
    ClaimConfirmRequest,
    ChooseRequest,
    CompareRequest,
    DecisionRequest,
    GoalUpdateRequest,
    ImportRequest,
    LearningOutcomeRequest,
    MemoryClaimRequest,
    MemoryEpisodeRequest,
    MemoryQueryRequest,
    TransformRequestModel,
)
from workbench_server.serialization import (
    claim_to_dict,
    decision_to_dict,
    diff_to_dict,
    finding_to_dict,
    note_to_dict,
    learning_state_to_dict,
    memory_event_to_dict,
    observation_to_dict,
    outcome_projection_to_dict,
    project_config_to_dict,
    project_state_to_dict,
    recall_view_to_dict,
    transform_result_to_dict,
)
from workbench_server.store import (
    ArtifactNotFound,
    VersionNotFound,
    decode_midi_b64,
    get_store,
    close_project_store,
    get_workspace_store,
    project_scope,
    request_project_id,
    ProjectNotFound,
)
from workbench_server.transcription import router as transcription_router
from workbench_server.projects import router as projects_router

@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    yield
    await shutdown_agent_manager()
    close_project_store()


app = FastAPI(title="Music Agent Workbench", version=__version__, lifespan=_lifespan)
app.include_router(transcription_router)
app.include_router(projects_router)


@app.middleware("http")
async def bind_request_project(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Capture project once, before a slow import/render or concurrent UI switch."""
    header = request.headers.get("x-workbench-project")
    query = request.query_params.get("project_id")
    if header and query and header != query:
        return JSONResponse(status_code=422, content=_error_envelope("conflicting project selectors"))
    workspace = get_workspace_store()
    project_id = header or query or workspace.active_project_id()
    if project_id is not None:
        try:
            workspace.project_config(project_id)
        except ProjectNotFound as exc:
            return JSONResponse(status_code=404, content=_error_envelope(str(exc)))
    with project_scope(project_id):
        return await call_next(request)


@app.exception_handler(RequestValidationError)
async def _request_validation_error_handler(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
    _request: Request, exc: RequestValidationError,
) -> JSONResponse:
    message = "; ".join(f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                        for error in exc.errors())
    return JSONResponse(status_code=422, content=_error_envelope(message))


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


@app.exception_handler(ProjectNotFound)
async def _project_not_found_handler(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
    _request: Request, exc: ProjectNotFound,
) -> JSONResponse:
    return JSONResponse(status_code=404, content=_error_envelope(str(exc)))


@app.exception_handler(ArtifactNotFound)
async def _artifact_not_found_handler(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
    _request: Request, exc: ArtifactNotFound
) -> JSONResponse:
    return JSONResponse(status_code=404, content=_error_envelope(str(exc)))


@app.exception_handler(MemoryRecordNotFound)
async def _memory_not_found_handler(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
    _request: Request, exc: MemoryRecordNotFound
) -> JSONResponse:
    return JSONResponse(status_code=404, content=_error_envelope(str(exc)))


@app.exception_handler(AgentTaskNotFound)
async def _agent_task_not_found_handler(  # pyright: ignore[reportUnusedFunction]  # registered via decorator
    _request: Request, exc: AgentTaskNotFound
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
    """Stream retained and live runtime events for ``?task_id=...`` subscribers."""
    await websocket.accept()
    task_id = websocket.query_params.get("task_id")
    await websocket.send_json(
        {
            "type": "hello",
            "payload": {
                "service": "workbench-server",
                "version": __version__,
                "task_id": task_id,
            },
        }
    )
    if task_id is None:
        try:
            while True:
                message = await websocket.receive_text()
                await websocket.send_json({"type": "echo", "payload": message})
        except WebSocketDisconnect:
            pass
        return
    manager = get_agent_manager()
    queue: asyncio.Queue[AgentTaskEvent] | None = None
    try:
        record = await manager.get(task_id)
        project_id = websocket.query_params.get("project_id") or get_workspace_store().active_project_id()
        if record.project_id is not None and record.project_id != project_id:
            raise AgentTaskNotFound(task_id)
        history, queue, terminal = await manager.subscribe(task_id)
        for event in history:
            await websocket.send_json(event.to_dict())
        while not terminal:
            event = await queue.get()
            await websocket.send_json(event.to_dict())
            terminal = event.type in {
                "runtime.completed",
                "runtime.cancelled",
                "runtime.error",
            }
    except AgentTaskNotFound as exc:
        await websocket.send_json(
            {"type": "runtime.error", "payload": {"message": str(exc)}}
        )
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        pass
    finally:
        if queue is not None:
            await manager.unsubscribe(task_id, queue)


# --------------------------------------------------------------------------- #
# Agent runtime tasks (design doc sections 6 and 9)
# --------------------------------------------------------------------------- #


@app.post("/api/agent/tasks", status_code=202)
async def agent_task_create(body: AgentTaskRequest) -> dict[str, Any]:
    """Delegate a new Analyze, Learn, or Experiment task to OpenCode."""
    record = await get_agent_manager().create(
        prompt=body.prompt, mode=body.mode, session_id=body.session_id, project_id=get_store().config.id
    )
    return envelope(
        {"task": record.to_dict()},
        tool="agent_task_create",
        inputs=[record.task_id],
        version=__version__,
    )


@app.get("/api/agent/tasks/{task_id}")
async def agent_task_get(task_id: str) -> dict[str, Any]:
    """Return retained status and events for an agent task."""
    record = await get_agent_manager().get(task_id)
    if record.project_id is not None and record.project_id != get_store().config.id:
        raise AgentTaskNotFound(task_id)
    return envelope(
        {"task": record.to_dict()},
        tool="agent_task_get",
        inputs=[task_id],
        version=__version__,
    )


@app.get("/api/agent/tasks")
async def agent_latest_task() -> dict[str, object]:
    record = await get_agent_manager().latest(get_store().config.id)
    return envelope({"task": record.to_dict() if record is not None else None}, tool="agent_latest_task")


@app.post("/api/agent/tasks/{task_id}/cancel")
async def agent_task_cancel(task_id: str) -> dict[str, Any]:
    """Cancel a running OpenCode subprocess without deleting retained events."""
    record = await get_agent_manager().get(task_id)
    if record.project_id is not None and record.project_id != get_store().config.id:
        raise AgentTaskNotFound(task_id)
    record = await get_agent_manager().cancel(task_id)
    return envelope(
        {"task": record.to_dict()},
        tool="agent_task_cancel",
        inputs=[task_id],
        version=__version__,
    )


@app.post("/api/agent/sessions/{session_id}/resume", status_code=202)
async def agent_session_resume(
    session_id: str, body: AgentResumeRequest
) -> dict[str, Any]:
    """Continue an OpenCode session as a new observable Workbench task."""
    record = await get_agent_manager().create(
        prompt=body.prompt, mode=body.mode, session_id=session_id, project_id=get_store().config.id
    )
    return envelope(
        {"task": record.to_dict()},
        tool="agent_session_resume",
        inputs=[session_id, record.task_id],
        version=__version__,
    )


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
    store.set_working_version(version.version_id)
    get_memory_store().record_project_state(
        actor_id="system:workbench",
        project_id=store.config.id,
        key="active_version",
        value=store.active_version_id(),
    )
    return envelope(
        {"version": version.to_dict()},
        tool="import_score",
        inputs=[version.version_id],
        version=__version__,
    )


@app.get("/api/score/{version_id}")
def score_get(
    version_id: str,
    start_beat: float | None = Query(default=None),
    end_beat: float | None = Query(default=None),
    track_ids: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=256, ge=1, le=1024),
) -> dict[str, Any]:
    """Return summary and a bounded note page for evidence-based inspection."""
    version = get_store().get_version(version_id)
    region = _score_region(version.document, start_beat, end_beat, track_ids)
    notes = version.document.select_region(region) if region else sorted(
        version.document.notes, key=lambda note: (note.onset_beats, note.track_id, note.pitch)
    )
    return envelope(
        {"version": version.to_dict(), "notes": [note_to_dict(note) for note in notes[offset:offset + limit]],
         "total_notes": len(notes), "offset": offset,
         "next_offset": offset + limit if offset + limit < len(notes) else None},
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
    region = _score_region(document, start_beat, end_beat, track_ids)
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
        out_path = Path(tmp) / f"{version_id}.wav"
        result = render_score(document, out_path, backend=backend,
                              soundfont=os.environ.get("WORKBENCH_SOUNDFONT"))
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
def artifact_get(token: str, request: Request) -> Response:
    """Download a previously produced artifact (render/export) by token."""
    record = get_store().get_artifact(token)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(record.filename)}",
               "Accept-Ranges": "bytes"}
    data = record.data
    total = len(data)
    range_header = request.headers.get("range")
    if range_header is not None:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
        if match is not None and (match[1] or match[2]):
            start = int(match[1]) if match[1] else max(0, total - int(match[2]))
            end = min(int(match[2]), total - 1) if match[1] and match[2] else total - 1
            if 0 <= start <= end < total:
                headers["Content-Range"] = f"bytes {start}-{end}/{total}"
                return Response(content=data[start:end + 1], status_code=206,
                                media_type=record.content_type, headers=headers)
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{total}"})
    return Response(
        content=data,
        media_type=record.content_type,
        headers=headers,
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
            "working_version": config.extra.get("working_version"),
            "storage": "sqlite",
        },
        tool="project_status",
        version=__version__,
    )


@app.patch("/api/project/goal")
def project_update_goal(body: GoalUpdateRequest) -> dict[str, Any]:
    """Set the current goal (description + optional bar/beat region)."""
    config = get_store().update_goal(body.description, body.bars, body.beats)
    get_memory_store().record_project_state(
        actor_id="person:user",
        project_id=config.id,
        key="current_goal",
        value={
            "description": body.description,
            "bars": list(body.bars) if body.bars is not None else None,
            "beats": list(body.beats) if body.beats is not None else None,
        },
    )
    return envelope(
        {"project": project_config_to_dict(config)},
        tool="project_update_goal",
        version=__version__,
    )


@app.post("/api/project/decision")
def project_record_decision(body: DecisionRequest) -> dict[str, Any]:
    """Append an explicit, audit-log-style decision to the project config."""
    store = get_store()
    if body.chosen_version_id is not None and not store.has_version(body.chosen_version_id):
        raise VersionNotFound(body.chosen_version_id)
    config, decision = store.record_decision(
        summary=body.summary,
        chosen_version_id=body.chosen_version_id,
        reason=body.reason,
        tags=tuple(body.tags),
    )
    get_memory_store().record_project_state(
        actor_id="person:user",
        project_id=config.id,
        key="last_decision",
        value={
            "id": decision.id,
            "summary": decision.summary,
            "chosen_version_id": decision.chosen_version_id,
            "reason": decision.reason,
            "tags": list(decision.tags),
        },
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
    get_memory_store().record_project_state(
        actor_id="person:user",
        project_id=config.id,
        key="active_version",
        value=body.version_id,
    )
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
    projection = get_memory_store().record_experiment_outcome(
        ExperimentOutcome(
            project_id=config.id,
            subject_id=body.subject_id,
            experiment_id=body.experiment_id or decision.id,
            chosen_version_id=body.chosen_version_id,
            reason=body.reason,
            learning_focus=body.learning_focus,
            tags=tuple(body.tags),
        )
    )
    return envelope(
        {
            "decision": decision_to_dict(decision),
            "project": project_config_to_dict(config),
            "memory_projection": outcome_projection_to_dict(projection),
        },
        tool="project_choose",
        inputs=[body.chosen_version_id],
        version=__version__,
    )


# --------------------------------------------------------------------------- #
# Memory and learning tools (design doc sections 8.3 and 11)
# --------------------------------------------------------------------------- #


@app.post("/api/memory/episodes")
def memory_record_episode(body: MemoryEpisodeRequest) -> dict[str, Any]:
    """Append an episode and expose its low-inference observation."""
    store = get_memory_store()
    event = store.record_episode(
        actor_id=body.actor_id,
        project_id=_memory_project(body.project_id),
        summary=body.summary,
        details=body.details,
    )
    observation = store.get_observation(f"observation:{event.id}")
    return envelope(
        {
            "event": memory_event_to_dict(event),
            "observation": observation_to_dict(observation),
        },
        tool="memory_record_episode",
        inputs=[body.project_id] if body.project_id else [],
        version=__version__,
    )


@app.post("/api/memory/claims")
def memory_propose_claim(body: MemoryClaimRequest) -> dict[str, Any]:
    """Create a proposal with evidence and a fail-closed policy."""
    store = get_memory_store()
    claim = store.propose_claim(
        actor_id=body.actor_id,
        project_id=_memory_project(body.project_id),
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        predicate=body.predicate,
        value=body.value,
        claim_type=body.claim_type,
        context_type=body.context_type,
        context_id=body.context_id,
        tags=tuple(body.tags),
        confidence=body.confidence,
        excerpt=body.excerpt,
        sensitivity=body.sensitivity,
        visibility=body.visibility,
        allowed_contexts=tuple(body.allowed_contexts),
    )
    return envelope(
        claim_to_dict(*store.get_claim(claim.id)),
        tool="memory_propose_claim",
        inputs=[body.project_id] if body.project_id else [],
        version=__version__,
    )


@app.post("/api/memory/claims/{claim_id}/confirm")
def memory_confirm_claim(
    claim_id: str, body: ClaimConfirmRequest
) -> dict[str, Any]:
    """Confirm a proposal only after an explicit user-facing command."""
    store = get_memory_store()
    try:
        store.confirm_claim(claim_id, actor_id=body.actor_id)
        result = store.get_claim(claim_id)
    except KeyError as exc:
        raise MemoryRecordNotFound(claim_id) from exc
    return envelope(
        claim_to_dict(*result),
        tool="memory_confirm_claim",
        inputs=[claim_id],
        version=__version__,
    )


@app.post("/api/memory/query")
def memory_query(body: MemoryQueryRequest) -> dict[str, Any]:
    """Plan channel-specific recall and return a ranked recall view."""
    plan = RecallPlanner().plan(
        project_id=_memory_project(body.project_id),
        subject_id=body.subject_id,
        need_raw_history=body.need_raw_history,
        time_horizon=body.time_horizon,
        per_channel_limit=body.per_channel_limit,
    )
    view = recall(get_memory_store(), plan, query=body.query)
    return envelope(
        recall_view_to_dict(view),
        tool="memory_query",
        inputs=[value for value in (body.project_id, body.subject_id) if value],
        version=__version__,
    )


@app.post("/api/learning/outcomes")
def learning_record_outcome(body: LearningOutcomeRequest) -> dict[str, Any]:
    """Record an explicit learning event and update current learning state."""
    state = get_memory_store().record_learning_outcome(
        actor_id=body.actor_id,
        subject_id=body.subject_id,
        project_id=_memory_project(body.project_id),
        focus=body.focus,
        status=body.status,
        mastery=body.mastery,
        evidence=body.evidence,
    )
    return envelope(
        {"learning_state": learning_state_to_dict(state)},
        tool="learning_record_outcome",
        inputs=[body.project_id] if body.project_id else [],
        version=__version__,
    )


@app.get("/api/memory/project/{project_id}")
def memory_project_state(project_id: str) -> dict[str, Any]:
    """Inspect explicit project and learning projections without raw history."""
    _memory_project(project_id)
    store = get_memory_store()
    return envelope(
        {
            "project_state": [
                project_state_to_dict(item) for item in store.list_project_state(project_id)
            ],
            "projection_counts": store.projection_counts(),
        },
        tool="memory_project_state",
        inputs=[project_id],
        version=__version__,
    )


# --------------------------------------------------------------------------- #
# Small shared helpers
# --------------------------------------------------------------------------- #

def _memory_project(project_id: str | None) -> str | None:
    selected = request_project_id()
    if selected is not None and project_id is not None and project_id != selected:
        raise ValueError("memory operation belongs to a different project")
    return project_id or selected

def _score_region(
    document: ScoreDocument, start_beat: float | None, end_beat: float | None,
    track_ids: str | None,
) -> Region | None:
    if (start_beat is None) != (end_beat is None):
        raise ValueError("inspect region requires both start_beat and end_beat")
    tids = tuple(value.strip() for value in track_ids.split(",") if value.strip()) if track_ids else None
    if tids and not set(tids) <= {note.track_id for note in document.notes}:
        raise ValueError("selection references an unknown note track")
    if start_beat is None and not tids:
        return None
    return Region(start_beat if start_beat is not None else 0.0,
                  end_beat if end_beat is not None else document.duration_beats, tids)

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
