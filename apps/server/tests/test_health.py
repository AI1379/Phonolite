"""Smoke tests for the Domain API skeleton."""

from __future__ import annotations

from fastapi.testclient import TestClient
from music_core import __version__ as music_core_version

from workbench_server.main import app

client = TestClient(app)


def test_health_returns_section_84_envelope() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()

    # Unified envelope shape (design doc section 8.4).
    assert body["ok"] is True
    assert body["warnings"] == []
    assert body["artifacts"] == []
    assert body["provenance"]["tool"] == "health"

    result = body["result"]
    assert result["service"] == "workbench-server"
    assert result["music_core_version"] == music_core_version


def test_websocket_greets_and_echoes() -> None:
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"

        ws.send_text("ping")
        echo = ws.receive_json()
        assert echo == {"type": "echo", "payload": "ping"}
