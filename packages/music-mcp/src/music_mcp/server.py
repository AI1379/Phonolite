"""stdio MCP server exposing the Workbench Domain API to OpenCode."""

from __future__ import annotations

import os
from collections.abc import Mapping

from mcp.server.fastmcp import FastMCP
from pydantic import JsonValue

from music_mcp.client import DomainApiClient
from music_mcp.client import JsonValue as ClientJsonValue

_DEFAULT_API_URL = "http://127.0.0.1:8000"
_client: DomainApiClient | None = None

mcp = FastMCP(
    "Music Agent Workbench",
    instructions=(
        "Use deterministic score tools before musical interpretation. "
        "Never claim a version was accepted unless the human-facing project API confirms it."
    ),
)


def get_client() -> DomainApiClient:
    global _client
    if _client is None:
        _client = DomainApiClient(os.environ.get("WORKBENCH_API_URL", _DEFAULT_API_URL),
                                  project_id=os.environ.get("WORKBENCH_PROJECT_ID"))
    return _client


def configure_client(client: DomainApiClient | None) -> None:
    """Replace the process client; tests use this without opening a socket."""
    global _client
    if _client is not None and _client is not client:
        _client.close()
    _client = client


@mcp.tool()
def project_status() -> dict[str, JsonValue]:
    """Get the current goal, active version, version tree, and explicit decisions."""
    return get_client().request("GET", "/api/project")


@mcp.tool()
def get_score(
    version_id: str, start_beat: float | None = None, end_beat: float | None = None,
    track_ids: str | None = None, offset: int = 0, limit: int = 256,
) -> dict[str, JsonValue]:
    """Read score metadata and paginated actual notes; use next_offset for more."""
    params: dict[str, str | float] = {"offset": offset, "limit": limit}
    if start_beat is not None:
        params["start_beat"] = start_beat
    if end_beat is not None:
        params["end_beat"] = end_beat
    if track_ids is not None:
        params["track_ids"] = track_ids
    return get_client().request("GET", f"/api/score/{version_id}", params=params)


@mcp.tool()
def inspect_score(
    version_id: str,
    start_beat: float | None = None,
    end_beat: float | None = None,
    track_ids: str | None = None,
) -> dict[str, JsonValue]:
    """Run deterministic, locatable score analysis over a score or beat region."""
    params: dict[str, str | float] = {}
    if start_beat is not None:
        params["start_beat"] = start_beat
    if end_beat is not None:
        params["end_beat"] = end_beat
    if track_ids is not None:
        params["track_ids"] = track_ids
    return get_client().request(
        "GET", f"/api/score/{version_id}/inspect", params=params
    )


@mcp.tool()
def compare_versions(
    before_version_id: str, after_version_id: str
) -> dict[str, JsonValue]:
    """Return a semantic note-level diff between two stored score versions."""
    return get_client().request(
        "POST",
        "/api/score/compare",
        body={
            "before_version_id": before_version_id,
            "after_version_id": after_version_id,
        },
    )


@mcp.tool()
def apply_transformation(
    source_version_id: str,
    start_beat: float,
    end_beat: float,
    operation: str,
    parameters: Mapping[str, str | int | float | bool] | None = None,
    output_branch: str | None = None,
    preserve: list[str] | None = None,
    vary: list[str] | None = None,
    track_ids: list[str] | None = None,
) -> dict[str, JsonValue]:
    """Create one experimental branch by changing one declared musical variable."""
    preserve_values: list[ClientJsonValue] = list(preserve or [])
    vary_values: list[ClientJsonValue] = list(vary or [])
    body: dict[str, ClientJsonValue] = {
        "source_version_id": source_version_id,
        "region": {"start_beat": start_beat, "end_beat": end_beat},
        "operation": operation,
        "parameters": dict(parameters or {}),
        "preserve": preserve_values,
        "vary": vary_values,
    }
    if output_branch is not None:
        body["output_branch"] = output_branch
    if track_ids is not None:
        body["region"] = {"start_beat": start_beat, "end_beat": end_beat,
                          "track_ids": list(track_ids)}
    return get_client().request("POST", "/api/score/transform", body=body)


@mcp.tool()
def render_score(version_id: str, backend: str = "preview") -> dict[str, JsonValue]:
    """Render a version to a downloadable audio or MIDI artifact."""
    return get_client().request(
        "POST", f"/api/score/{version_id}/render", params={"backend": backend}
    )


@mcp.tool()
def export_score(version_id: str) -> dict[str, JsonValue]:
    """Export a score version as a downloadable Standard MIDI File artifact."""
    return get_client().request("POST", f"/api/score/{version_id}/export")


@mcp.tool()
def memory_query(
    query: str = "",
    project_id: str | None = None,
    subject_id: str | None = "user",
    time_horizon: str = "long",
    per_channel_limit: int = 5,
) -> dict[str, JsonValue]:
    """Recall bounded, policy-filtered memory channels without raw history."""
    return get_client().request(
        "POST",
        "/api/memory/query",
        body={
            "query": query,
            "project_id": project_id,
            "subject_id": subject_id,
            "need_raw_history": False,
            "time_horizon": time_horizon,
            "per_channel_limit": per_channel_limit,
        },
    )


@mcp.tool()
def memory_record_episode(
    summary: str,
    project_id: str | None = None,
    actor_id: str = "agent:opencode",
    details: Mapping[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    """Append a factual project episode; do not infer a long-term preference."""
    return get_client().request(
        "POST",
        "/api/memory/episodes",
        body={
            "actor_id": actor_id,
            "project_id": project_id,
            "summary": summary,
            "details": dict(details or {}),
        },
    )


@mcp.tool()
def learning_record_outcome(
    focus: str,
    status: str,
    mastery: float,
    evidence: str,
    project_id: str | None = None,
    subject_id: str = "user",
    actor_id: str = "agent:opencode",
) -> dict[str, JsonValue]:
    """Record an evidence-backed learning outcome explicitly stated in the session."""
    return get_client().request(
        "POST",
        "/api/learning/outcomes",
        body={
            "actor_id": actor_id,
            "subject_id": subject_id,
            "project_id": project_id,
            "focus": focus,
            "status": status,
            "mastery": mastery,
            "evidence": evidence,
        },
    )


def main() -> None:
    """Console entry point used by OpenCode's local MCP configuration."""
    mcp.run(transport="stdio")


__all__ = ["configure_client", "get_client", "main", "mcp"]
