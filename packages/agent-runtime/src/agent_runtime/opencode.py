"""OpenCode CLI implementation of the host-neutral agent runtime protocol."""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import cast

from agent_runtime.models import JsonValue, RuntimeEvent, RuntimeTask

_PROFILE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
_MAX_STDERR_LINES = 50


class OpenCodeRuntimeError(RuntimeError):
    """Raised when an OpenCode process cannot be started safely."""


def _json_object(value: object) -> dict[str, JsonValue]:
    """Narrow a decoded JSON object without allowing ``Any`` across the boundary."""
    if not isinstance(value, dict):
        raise ValueError("OpenCode event must be a JSON object")
    normalized: dict[str, JsonValue] = {}
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str):
            raise ValueError("OpenCode event keys must be strings")
        normalized[key] = _json_value(item)
    return normalized


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in cast(list[object], value)]
    if isinstance(value, dict):
        return _json_object(value)
    raise ValueError(f"unsupported JSON value from OpenCode: {type(value).__name__}")


class OpenCodeRuntime:
    """Run OpenCode as a subprocess and preserve its newline-delimited events.

    ``opencode run --format json`` deliberately remains behind this adapter.
    The application sees only :class:`RuntimeEvent`, and can later switch to
    the OpenCode server API or another runtime without changing task routing.
    """

    def __init__(
        self,
        *,
        command: Sequence[str] = ("opencode",),
        default_workspace: str | Path | None = None,
        domain_api_url: str = "http://127.0.0.1:8000",
        model: str | None = None,
        attach_url: str | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not command:
            raise ValueError("OpenCode command cannot be empty")
        self._command = tuple(command)
        self._default_workspace = str(Path(default_workspace or Path.cwd()).resolve())
        self._domain_api_url = domain_api_url.rstrip("/")
        self._model = model
        self._attach_url = attach_url
        self._environment = dict(environment or {})
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._cancelled: set[str] = set()
        self._lock = asyncio.Lock()

    def run(self, task: RuntimeTask) -> AsyncIterator[RuntimeEvent]:
        return self._run_task(task)

    def resume(self, session_id: str, prompt: str) -> AsyncIterator[RuntimeEvent]:
        task = RuntimeTask(
            task_id=f"resume-{uuid.uuid4().hex}",
            prompt=prompt,
            workspace=self._default_workspace,
            session_id=session_id,
        )
        return self._run_task(task)

    async def cancel(self, task_id: str) -> None:
        async with self._lock:
            self._cancelled.add(task_id)
            process = self._processes.get(task_id)
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def _run_task(self, task: RuntimeTask) -> AsyncIterator[RuntimeEvent]:
        if not task.prompt.strip():
            raise ValueError("runtime prompt cannot be empty")
        if not _PROFILE_RE.fullmatch(task.tool_profile):
            raise ValueError(f"invalid OpenCode agent profile: {task.tool_profile!r}")
        workspace = str(Path(task.workspace).resolve())
        if not Path(workspace).is_dir():
            raise ValueError(f"runtime workspace does not exist: {workspace}")
        project_id = task.metadata.get("project_id")
        if isinstance(project_id, str) and self._attach_url is not None:
            raise OpenCodeRuntimeError("Project-bound tasks require a dedicated CLI process; unset WORKBENCH_OPENCODE_ATTACH")

        args = [*self._command, "run", "--format", "json", "--dir", workspace]
        if task.session_id is not None:
            args.extend(("--session", task.session_id))
        if self._model is not None:
            args.extend(("--model", self._model))
        if self._attach_url is not None:
            args.extend(("--attach", self._attach_url))
        args.extend(("--agent", task.tool_profile, "--", task.prompt))

        environment = os.environ.copy()
        environment.update(self._environment)
        environment["WORKBENCH_API_URL"] = self._domain_api_url
        if isinstance(project_id, str):
            environment["WORKBENCH_PROJECT_ID"] = project_id
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=workspace,
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise OpenCodeRuntimeError(f"unable to start OpenCode: {exc}") from exc

        async with self._lock:
            if task.task_id in self._processes:
                process.terminate()
                await process.wait()
                raise OpenCodeRuntimeError(f"task is already running: {task.task_id}")
            self._processes[task.task_id] = process
            cancel_immediately = task.task_id in self._cancelled
        if cancel_immediately:
            process.terminate()

        stderr_task = asyncio.create_task(self._read_stderr(process))
        session_id = task.session_id
        try:
            if process.stdout is None:
                raise OpenCodeRuntimeError("OpenCode stdout pipe is unavailable")
            while line_bytes := await process.stdout.readline():
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    decoded = json.loads(line)
                    payload = _json_object(decoded)
                except (json.JSONDecodeError, ValueError) as exc:
                    yield RuntimeEvent(
                        type="runtime.protocol_warning",
                        payload={"message": str(exc), "line": line},
                    )
                    continue
                raw_type = payload.get("type")
                event_type = raw_type if isinstance(raw_type, str) else "opencode.event"
                raw_session_id = payload.get("sessionID")
                if isinstance(raw_session_id, str):
                    session_id = raw_session_id
                yield RuntimeEvent(type=event_type, payload=payload)

            return_code = await process.wait()
            stderr_lines = await stderr_task
            if task.task_id in self._cancelled:
                yield RuntimeEvent(
                    type="runtime.cancelled",
                    payload={"task_id": task.task_id, "session_id": session_id},
                )
            elif return_code == 0:
                yield RuntimeEvent(
                    type="runtime.completed",
                    payload={"task_id": task.task_id, "session_id": session_id},
                )
            else:
                yield RuntimeEvent(
                    type="runtime.error",
                    payload={
                        "task_id": task.task_id,
                        "session_id": session_id,
                        "exit_code": return_code,
                        "stderr": "\n".join(stderr_lines),
                    },
                )
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            if not stderr_task.done():
                stderr_task.cancel()
                try:
                    await stderr_task
                except asyncio.CancelledError:
                    pass
            async with self._lock:
                self._processes.pop(task.task_id, None)
                self._cancelled.discard(task.task_id)

    @staticmethod
    async def _read_stderr(process: asyncio.subprocess.Process) -> list[str]:
        if process.stderr is None:
            return []
        lines: list[str] = []
        while line_bytes := await process.stderr.readline():
            line = line_bytes.decode("utf-8", errors="replace").rstrip()
            if line:
                lines.append(line)
                if len(lines) > _MAX_STDERR_LINES:
                    lines.pop(0)
        return lines


__all__ = ["OpenCodeRuntime", "OpenCodeRuntimeError"]
