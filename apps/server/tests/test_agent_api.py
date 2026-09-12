"""Agent task API and WebSocket tests using a deterministic fake runtime."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from agent_runtime import RuntimeEvent, RuntimeTask
from fastapi.testclient import TestClient

from workbench_server.agent import configure_agent_runtime


class FakeRuntime:
    """Records routing profiles and emits the same terminal contract as OpenCode."""

    def __init__(self, *, blocking: bool = False) -> None:
        self.tasks: list[RuntimeTask] = []
        self._blocking = blocking
        self._cancelled: set[str] = set()

    async def _events(self, task: RuntimeTask) -> AsyncIterator[RuntimeEvent]:
        self.tasks.append(task)
        session_id = task.session_id or "ses-fake"
        yield RuntimeEvent(
            type="step_start", payload={"sessionID": session_id, "type": "step_start"}
        )
        if self._blocking:
            while task.task_id not in self._cancelled:
                await asyncio.sleep(0.01)
            yield RuntimeEvent(
                type="runtime.cancelled",
                payload={"task_id": task.task_id, "session_id": session_id},
            )
            return
        yield RuntimeEvent(
            type="text",
            payload={
                "sessionID": session_id,
                "type": "text",
                "part": {"type": "text", "text": "grounded result"},
            },
        )
        yield RuntimeEvent(
            type="runtime.completed",
            payload={"task_id": task.task_id, "session_id": session_id},
        )

    def run(self, task: RuntimeTask) -> AsyncIterator[RuntimeEvent]:
        return self._events(task)

    async def cancel(self, task_id: str) -> None:
        self._cancelled.add(task_id)

    def resume(self, session_id: str, prompt: str) -> AsyncIterator[RuntimeEvent]:
        return self._events(
            RuntimeTask(
                task_id="resume-fake",
                prompt=prompt,
                workspace=".",
                session_id=session_id,
            )
        )


def _wait_for_status(client: TestClient, task_id: str, status: str) -> dict[str, object]:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        response = client.get(f"/api/agent/tasks/{task_id}")
        assert response.status_code == 200
        task: dict[str, object] = response.json()["result"]["task"]
        if task["status"] == status:
            return task
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not reach {status}")


def test_agent_task_routes_mode_and_replays_events_to_websocket(
    client: TestClient,
) -> None:
    runtime = FakeRuntime()
    configure_agent_runtime(runtime)
    created = client.post(
        "/api/agent/tasks", json={"prompt": "Analyze the active score", "mode": "analyze"}
    )
    assert created.status_code == 202
    task_id = created.json()["result"]["task"]["task_id"]
    completed = _wait_for_status(client, task_id, "completed")
    assert completed["session_id"] == "ses-fake"
    assert runtime.tasks[0].permission_profile == "read_only"
    assert runtime.tasks[0].tool_profile == "workbench-analyze"

    with client.websocket_connect(f"/ws?task_id={task_id}") as websocket:
        assert websocket.receive_json()["type"] == "hello"
        event_types: list[str] = []
        while "runtime.completed" not in event_types:
            event_types.append(websocket.receive_json()["type"])
    assert event_types == ["step_start", "text", "runtime.completed"]


def test_agent_session_resume_preserves_session_and_mode(client: TestClient) -> None:
    runtime = FakeRuntime()
    configure_agent_runtime(runtime)
    started = client.post("/api/agent/tasks", json={"prompt": "Begin this project", "mode": "analyze"}).json()["result"]["task"]
    completed = _wait_for_status(client, str(started["task_id"]), "completed")
    session_id = str(completed["session_id"])
    response = client.post(
        f"/api/agent/sessions/{session_id}/resume",
        json={"prompt": "Now propose an experiment", "mode": "experiment"},
    )
    assert response.status_code == 202
    task_id = response.json()["result"]["task"]["task_id"]
    _wait_for_status(client, task_id, "completed")
    assert runtime.tasks[1].session_id == session_id
    assert runtime.tasks[1].permission_profile == "experiment_write"
    assert runtime.tasks[1].tool_profile == "workbench-experiment"


def test_agent_task_can_be_cancelled(client: TestClient) -> None:
    runtime = FakeRuntime(blocking=True)
    configure_agent_runtime(runtime)
    created = client.post(
        "/api/agent/tasks", json={"prompt": "Teach this passage", "mode": "learn"}
    ).json()
    task_id = created["result"]["task"]["task_id"]
    _wait_for_status(client, task_id, "running")
    cancelled = client.post(f"/api/agent/tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    final = _wait_for_status(client, task_id, "cancelled")
    assert final["status"] == "cancelled"


def test_unknown_agent_task_returns_envelope_404(client: TestClient) -> None:
    response = client.get("/api/agent/tasks/missing")
    assert response.status_code == 404
    assert response.json()["ok"] is False

    with client.websocket_connect("/ws?task_id=missing") as websocket:
        assert websocket.receive_json()["type"] == "hello"
        error = websocket.receive_json()
        assert error["type"] == "runtime.error"
        assert "not found" in error["payload"]["message"]


def test_agent_task_and_session_remain_bound_after_project_switch(client: TestClient) -> None:
    a = client.post("/api/projects", json={"title": "A"}).json()["result"]["project"]["id"]
    runtime = FakeRuntime()
    configure_agent_runtime(runtime)
    task = client.post("/api/agent/tasks", json={"prompt": "Inspect A", "mode": "analyze"}).json()["result"]["task"]
    done = _wait_for_status(client, task["task_id"], "completed")
    assert runtime.tasks[0].metadata["project_id"] == a
    client.post("/api/projects", json={"title": "B"})
    assert client.get("/api/agent/tasks").json()["result"]["task"] is None
    assert client.get(f"/api/agent/tasks/{task['task_id']}").status_code == 404
    assert client.post(f"/api/agent/sessions/{done['session_id']}/resume", json={"prompt":"continue"}).status_code == 422
    assert client.get(f"/api/agent/tasks/{task['task_id']}", headers={"X-Workbench-Project":a}).status_code == 200
    assert client.get("/api/agent/tasks", headers={"X-Workbench-Project":a}).json()["result"]["task"]["task_id"] == task["task_id"]
