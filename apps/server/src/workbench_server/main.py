"""Workbench server entry point.

Serves the Domain API (``/api/*``) and the event WebSocket (``/ws``) that
the Music Workbench UI (and later DAW bridges) talk to. Run with:

    uv run workbench-server        # 127.0.0.1:8000, auto-reload
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from music_core import __version__ as music_core_version
from typing import Any

from workbench_server import __version__
from workbench_server.envelope import envelope

app = FastAPI(title="Music Agent Workbench", version=__version__)


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Liveness probe; also proves the workspace wiring (music-core import)."""
    return envelope(
        {
            "service": "workbench-server",
            "version": __version__,
            "music_core_version": music_core_version,
        },
        tool="health",
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


def run() -> None:
    """Console-script entry point (``uv run workbench-server``)."""
    uvicorn.run("workbench_server.main:app", host="127.0.0.1", port=8000, reload=True)
