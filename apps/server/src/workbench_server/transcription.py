"""Reference-audio and manual-transcription Domain API routes."""

from __future__ import annotations

import base64
import binascii
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from music_core.edit import NoteValues, align_score, create_draft, edit_note
from music_core.reference import AlignmentAnchor, ScoreReference
from music_core.validation import validate_document
from workbench_server.assets import ReferenceRecord, prepare_audio
from workbench_server.envelope import envelope
from workbench_server.serialization import validation_to_dict
from workbench_server.store import get_store
from workbench_server.video import prepare_video

router = APIRouter()


class AudioImportRequest(BaseModel):
    audio_b64: str = Field(max_length=90 * 1024 * 1024)
    filename: str = Field(min_length=1, max_length=240)


class VideoImportRequest(BaseModel):
    video_b64: str = Field(max_length=350 * 1024 * 1024)
    filename: str = Field(min_length=1, max_length=240)


class AnchorInput(BaseModel):
    seconds: float = Field(ge=0, allow_inf_nan=False)
    beat: float = Field(ge=0, allow_inf_nan=False)


class AlignmentRequest(BaseModel):
    anchors: list[AnchorInput] = Field(min_length=2, max_length=64)


class DraftRequest(BaseModel):
    title: str = Field(default="Transcription draft", min_length=1, max_length=240)
    reference_id: str | None = None
    length_beats: float = Field(default=32, ge=1, le=4096, allow_inf_nan=False)
    bpm: float = Field(default=80, ge=10, le=600, allow_inf_nan=False)
    numerator: int = Field(default=4, ge=1, le=32)
    denominator: Literal[1, 2, 4, 8, 16, 32] = 4


class NoteInput(BaseModel):
    pitch: int = Field(ge=0, le=127)
    onset_beats: float = Field(ge=0, allow_inf_nan=False)
    duration_beats: float = Field(gt=0, allow_inf_nan=False)
    velocity: int = Field(default=80, ge=1, le=127)
    track_id: str = Field(default="melody", min_length=1, max_length=120)
    role: Literal["melody", "bass", "inner", "unknown"] = "melody"
    transcription_status: Literal["uncertain", "confirmed"] = "uncertain"

    def values(self) -> NoteValues:
        return NoteValues(self.pitch, self.onset_beats, self.duration_beats, self.velocity,
                          self.track_id, self.role, self.transcription_status)


class EditRequest(BaseModel):
    source_version_id: str
    action: Literal["add", "update", "remove"]
    note_id: str | None = None
    note: NoteInput | None = None


class AttachReferenceRequest(BaseModel):
    reference_id: str


def reference_to_dict(record: ReferenceRecord) -> dict[str, object]:
    return {"id": record.id, "filename": record.filename, "sha256": record.sha256,
            "duration_seconds": record.duration_seconds, "sample_rate": record.sample_rate,
            "channels": record.channels, "original_token": record.original_token,
            "playback_token": record.playback_token, "peaks": [list(pair) for pair in record.peaks],
            "media_kind": record.media_kind, "video_token": record.video_token,
            "video_width": record.video_width, "video_height": record.video_height,
            "has_audio": record.has_audio, "warnings": list(record.warnings),
            "anchors": [{"seconds": anchor.seconds, "beat": anchor.beat} for anchor in record.anchors]}


@router.post("/api/references/import")
def reference_import(body: AudioImportRequest) -> dict[str, object]:
    try:
        raw = base64.b64decode(body.audio_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 audio payload") from exc
    record = get_store().add_reference(prepare_audio(raw, body.filename))
    return envelope({"reference": reference_to_dict(record)}, tool="reference_import")


@router.get("/api/references")
def references_list() -> dict[str, object]:
    return envelope({"references": [reference_to_dict(record) for record in get_store().list_references()]}, tool="references_list")


@router.post("/api/references/import-video")
def reference_video_import(body: VideoImportRequest) -> dict[str, object]:
    try:
        raw = base64.b64decode(body.video_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 video payload") from exc
    record = get_store().add_reference(prepare_video(raw, body.filename))
    return envelope({"reference": reference_to_dict(record)}, tool="reference_video_import")


@router.put("/api/references/{reference_id}/alignment")
def reference_alignment(reference_id: str, body: AlignmentRequest) -> dict[str, object]:
    record = get_store().update_alignment(reference_id, tuple(AlignmentAnchor(item.seconds, item.beat) for item in body.anchors))
    return envelope({"reference": reference_to_dict(record)}, tool="reference_alignment")


def _reference(reference_id: str | None) -> ScoreReference | None:
    if reference_id is None:
        return None
    record = get_store().get_reference(reference_id)
    return ScoreReference(record.id, record.anchors)


@router.post("/api/score/draft")
def draft_create(body: DraftRequest) -> dict[str, object]:
    store = get_store()
    doc = create_draft(title=body.title, length_beats=body.length_beats, bpm=body.bpm,
                       numerator=body.numerator, denominator=body.denominator, reference=_reference(body.reference_id))
    version = store.add_version(doc, parent_id=None, branch="draft", origin="draft", description=body.title)
    if store.active_version_id() is None:
        store.accept_variant(doc.id)
    store.set_working_version(doc.id)
    return envelope({"version": version.to_dict()}, tool="draft_create")


@router.post("/api/score/edit")
def score_edit(body: EditRequest) -> dict[str, object]:
    store = get_store()
    source = store.get_version(body.source_version_id).document
    doc = edit_note(source, action=body.action, note_id=body.note_id, values=body.note.values() if body.note else None)
    version = store.add_version(doc, parent_id=source.id, branch="draft/edit", origin="edit", description=f"Manual note {body.action}")
    store.set_working_version(doc.id)
    return envelope({"version": version.to_dict(), "validation": validation_to_dict(validate_document(doc))}, tool="score_edit")


@router.post("/api/score/{version_id}/reference")
def score_attach_reference(version_id: str, body: AttachReferenceRequest) -> dict[str, object]:
    store = get_store()
    source = store.get_version(version_id).document
    reference = _reference(body.reference_id)
    assert reference is not None
    doc = align_score(source, reference)
    version = store.add_version(doc, parent_id=source.id, branch="draft/aligned", origin="edit", description="Aligned draft to marked reference audio")
    store.set_working_version(doc.id)
    return envelope({"version": version.to_dict()}, tool="score_attach_reference")
