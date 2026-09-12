"""Process-level tests for the OpenCode CLI adapter."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
import pytest

from agent_runtime import OpenCodeRuntime, RuntimeTask
from agent_runtime.opencode import OpenCodeRuntimeError


def _write_fake_runtime(path: Path) -> None:
    path.write_text(
        """
import json
import sys
import time

args = sys.argv[1:]
session = "existing" if "--session" in args else "created"
print(json.dumps({"type": "step_start", "sessionID": session}), flush=True)
if "WAIT_FOR_CANCEL" in args[-1]:
    time.sleep(30)
else:
    print(json.dumps({"type": "text", "sessionID": session,
                      "part": {"type": "text", "text": "done"}}), flush=True)
""".strip(),
        encoding="utf-8",
    )


def test_run_streams_json_events_and_terminal_event(tmp_path: Path) -> None:
    script = tmp_path / "fake_opencode.py"
    _write_fake_runtime(script)
    runtime = OpenCodeRuntime(command=(sys.executable, str(script)))
    task = RuntimeTask(task_id="task-1", prompt="analyze", workspace=str(tmp_path))

    async def collect() -> list[str]:
        return [event.type async for event in runtime.run(task)]

    assert asyncio.run(collect()) == ["step_start", "text", "runtime.completed"]


def test_run_passes_existing_session(tmp_path: Path) -> None:
    script = tmp_path / "fake_opencode.py"
    _write_fake_runtime(script)
    runtime = OpenCodeRuntime(command=(sys.executable, str(script)))
    task = RuntimeTask(
        task_id="task-2",
        prompt="continue",
        workspace=str(tmp_path),
        session_id="existing",
    )

    async def collect_session() -> str | None:
        async for event in runtime.run(task):
            session_id = event.payload.get("sessionID")
            if isinstance(session_id, str):
                return session_id
        return None

    assert asyncio.run(collect_session()) == "existing"


def test_cancel_terminates_running_process(tmp_path: Path) -> None:
    script = tmp_path / "fake_opencode.py"
    _write_fake_runtime(script)
    runtime = OpenCodeRuntime(command=(sys.executable, str(script)))
    task = RuntimeTask(
        task_id="task-cancel", prompt="WAIT_FOR_CANCEL", workspace=str(tmp_path)
    )

    async def run_and_cancel() -> list[str]:
        started = asyncio.Event()
        events: list[str] = []

        async def consume() -> None:
            async for event in runtime.run(task):
                events.append(event.type)
                if event.type == "step_start":
                    started.set()

        consumer = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=5.0)
        await runtime.cancel(task.task_id)
        await asyncio.wait_for(consumer, timeout=5.0)
        return events

    assert asyncio.run(run_and_cancel())[-1] == "runtime.cancelled"


def test_project_binding_reaches_the_mcp_child_environment(tmp_path: Path) -> None:
    script = tmp_path / "environment.py"
    script.write_text('import os,json\nprint(json.dumps({"type":"project", "project_id":os.environ.get("WORKBENCH_PROJECT_ID")}))', encoding="utf-8")
    runtime = OpenCodeRuntime(command=(sys.executable, str(script)), environment={"WORKBENCH_PROJECT_ID": "old-project"})
    task = RuntimeTask(task_id="project-env", prompt="inspect", workspace=str(tmp_path), metadata={"project_id":"project-a"})
    async def read_project() -> object:
        events = [event async for event in runtime.run(task)]
        return events[0].payload["project_id"]
    assert asyncio.run(read_project()) == "project-a"


def test_attached_host_cannot_silently_reuse_another_projects_mcp_environment(tmp_path: Path) -> None:
    runtime = OpenCodeRuntime(attach_url="http://127.0.0.1:1")
    task = RuntimeTask(task_id="project-attach", prompt="inspect", workspace=str(tmp_path), metadata={"project_id":"project-a"})
    async def run() -> None:
        async for _event in runtime.run(task):
            pass
    with pytest.raises(OpenCodeRuntimeError, match="dedicated CLI"):
        asyncio.run(run())
