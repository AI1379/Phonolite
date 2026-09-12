"""Tests for the typed Domain API proxy used by MCP tools."""

from __future__ import annotations

import json

import httpx
import pytest

from music_mcp import DomainApiClient, DomainApiError


def test_client_preserves_success_envelope_and_request_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/score/compare"
        assert json.loads(request.content) == {
            "before_version_id": "a",
            "after_version_id": "b",
        }
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"modified": []},
                "warnings": [],
                "artifacts": [],
                "provenance": {"tool": "compare_versions"},
            },
        )

    client = DomainApiClient("http://workbench", transport=httpx.MockTransport(handler))
    result = client.request(
        "POST",
        "/api/score/compare",
        body={"before_version_id": "a", "after_version_id": "b"},
    )
    assert result["ok"] is True
    client.close()


def test_client_turns_failed_envelope_into_tool_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"ok": False, "result": {}, "warnings": ["version not found"]},
        )

    client = DomainApiClient("http://workbench", transport=httpx.MockTransport(handler))
    with pytest.raises(DomainApiError, match="version not found"):
        client.request("GET", "/api/score/missing")
    client.close()


def test_client_pins_project_and_rejects_cross_project_memory() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Workbench-Project"] == "project-a"
        assert json.loads(request.content)["project_id"] == "project-a"
        return httpx.Response(200, json={"ok": True, "result": {}})
    client = DomainApiClient("http://workbench", transport=httpx.MockTransport(handler), project_id="project-a")
    client.request("POST", "/api/memory/query", body={"project_id": None})
    with pytest.raises(DomainApiError, match="differs"):
        client.request("POST", "/api/memory/query", body={"project_id": "project-b"})
    client.close()
