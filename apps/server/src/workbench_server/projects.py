"""Project catalog operations, distinct from the active project's version history."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from workbench_server.envelope import envelope
from workbench_server.serialization import project_config_to_dict
from workbench_server.store import get_workspace_store

router = APIRouter()


class ProjectCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    workflow: Literal["composition", "transcription"] = "transcription"


class ProjectRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)


@router.get("/api/projects")
def project_catalog() -> dict[str, object]:
    store = get_workspace_store()
    return envelope({"projects": store.list_projects(), "active_project_id": store.active_project_id()}, tool="project_catalog")


@router.post("/api/projects", status_code=201)
def project_create(body: ProjectCreateRequest) -> dict[str, object]:
    config = get_workspace_store().create_project(body.title, workflow=body.workflow)
    return envelope({"project": project_config_to_dict(config)}, tool="project_create")


@router.post("/api/projects/{project_id}/open")
def project_open(project_id: str) -> dict[str, object]:
    config = get_workspace_store().open_project(project_id)
    return envelope({"project": project_config_to_dict(config)}, tool="project_open")


@router.patch("/api/projects/{project_id}")
def project_rename(project_id: str, body: ProjectRenameRequest) -> dict[str, object]:
    config = get_workspace_store().rename_project(project_id, body.title)
    return envelope({"project": project_config_to_dict(config)}, tool="project_rename")
