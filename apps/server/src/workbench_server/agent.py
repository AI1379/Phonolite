"""Application-owned task lifecycle for the replaceable agent runtime."""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Literal, TypeAlias

from agent_runtime import AgentRuntime, JsonValue, OpenCodeRuntime, RuntimeEvent, RuntimeTask
from workbench_server.store import get_workspace_store

AgentMode: TypeAlias = Literal["analyze", "learn", "experiment"]
AgentTaskStatus: TypeAlias = Literal[
    "queued", "running", "cancelling", "completed", "failed", "cancelled"
]

_TERMINAL_STATUSES: Final[set[str]] = {"completed", "failed", "cancelled"}
_MODE_PROFILES: Final[dict[AgentMode, tuple[str, str]]] = {
    "analyze": ("read_only", "workbench-analyze"),
    "learn": ("analysis_write", "workbench-learn"),
    "experiment": ("experiment_write", "workbench-experiment"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class AgentTaskNotFound(KeyError):
    """Raised when an API command references an unknown agent task."""

    def __init__(self, task_id: str) -> None:
        super().__init__(task_id)
        self.task_id = task_id

    def __str__(self) -> str:
        return f"agent task not found: {self.task_id}"


@dataclass(frozen=True)
class AgentTaskEvent:
    """Sequenced event retained for late WebSocket subscribers."""

    sequence: int
    type: str
    payload: dict[str, JsonValue]
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "type": self.type,
            "payload": self.payload,
            "created_at": self.created_at,
        }


@dataclass
class AgentTaskRecord:
    """Observable application state for one delegated runtime task."""

    task_id: str
    prompt: str
    mode: AgentMode
    status: AgentTaskStatus
    workspace: str
    session_id: str | None
    created_at: str
    updated_at: str
    project_id: str | None = None
    events: list[AgentTaskEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "prompt": self.prompt,
            "mode": self.mode,
            "status": self.status,
            "workspace": self.workspace,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "project_id": self.project_id,
            "events": [event.to_dict() for event in self.events],
        }

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES


class AgentTaskManager:
    """Run, retain, broadcast, resume, and cancel agent runtime tasks."""

    def __init__(self, runtime: AgentRuntime, *, workspace: str | Path) -> None:
        self._runtime = runtime
        self._workspace = str(Path(workspace).resolve())
        self._records: dict[str, AgentTaskRecord] = {}
        self._runners: dict[str, asyncio.Task[None]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[AgentTaskEvent]]] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        prompt: str,
        mode: AgentMode,
        session_id: str | None = None,
        project_id: str | None = None,
    ) -> AgentTaskRecord:
        if session_id is not None and project_id is not None:
            if get_workspace_store().session_project(session_id) != project_id:
                raise ValueError("Session is unknown or belongs to another project; start a new session")
        task_id = f"task-{uuid.uuid4().hex}"
        now = _now_iso()
        record = AgentTaskRecord(
            task_id=task_id,
            prompt=prompt,
            mode=mode,
            status="queued",
            workspace=self._workspace,
            session_id=session_id,
            created_at=now,
            updated_at=now,
            project_id=project_id,
        )
        async with self._lock:
            self._records[task_id] = record
            self._runners[task_id] = asyncio.create_task(self._execute(record))
        return record

    async def get(self, task_id: str) -> AgentTaskRecord:
        async with self._lock:
            record = self._records.get(task_id)
            if record is None:
                raise AgentTaskNotFound(task_id)
            return record

    async def latest(self, project_id: str) -> AgentTaskRecord | None:
        async with self._lock:
            return next((record for record in reversed(list(self._records.values())) if record.project_id == project_id), None)

    async def cancel(self, task_id: str) -> AgentTaskRecord:
        record = await self.get(task_id)
        if record.terminal:
            return record
        record.status = "cancelling"
        record.updated_at = _now_iso()
        await self._runtime.cancel(task_id)
        return record

    async def subscribe(
        self, task_id: str
    ) -> tuple[list[AgentTaskEvent], asyncio.Queue[AgentTaskEvent], bool]:
        queue: asyncio.Queue[AgentTaskEvent] = asyncio.Queue()
        async with self._lock:
            record = self._records.get(task_id)
            if record is None:
                raise AgentTaskNotFound(task_id)
            self._subscribers.setdefault(task_id, set()).add(queue)
            return list(record.events), queue, record.terminal

    async def unsubscribe(
        self, task_id: str, queue: asyncio.Queue[AgentTaskEvent]
    ) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(task_id)
            if subscribers is None:
                return
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(task_id, None)

    async def shutdown(self) -> None:
        """Cancel live work and wait for runner cleanup (used by tests/lifespan)."""
        async with self._lock:
            active = [record.task_id for record in self._records.values() if not record.terminal]
            runners = list(self._runners.values())
        for task_id in active:
            await self._runtime.cancel(task_id)
        if runners:
            await asyncio.gather(*runners, return_exceptions=True)

    async def _execute(self, record: AgentTaskRecord) -> None:
        permission_profile, tool_profile = _MODE_PROFILES[record.mode]
        task = RuntimeTask(
            task_id=record.task_id,
            prompt=record.prompt,
            workspace=record.workspace,
            session_id=record.session_id,
            permission_profile=permission_profile,
            tool_profile=tool_profile,
            metadata={"mode": record.mode, "project_id": record.project_id},
        )
        if record.status != "cancelling":
            record.status = "running"
        record.updated_at = _now_iso()
        try:
            async for event in self._runtime.run(task):
                self._capture_session(record, event)
                if event.type == "runtime.completed":
                    record.status = "completed"
                elif event.type == "runtime.cancelled":
                    record.status = "cancelled"
                elif event.type == "runtime.error":
                    record.status = "failed"
                await self._append(record, event)
            if not record.terminal:
                record.status = "failed"
                await self._append(
                    record,
                    RuntimeEvent(
                        type="runtime.error",
                        payload={"message": "runtime ended without a terminal event"},
                    ),
                )
        except Exception as exc:
            record.status = "failed"
            await self._append(
                record,
                RuntimeEvent(type="runtime.error", payload={"message": str(exc)}),
            )
        finally:
            record.updated_at = _now_iso()
            async with self._lock:
                self._runners.pop(record.task_id, None)

    @staticmethod
    def _capture_session(record: AgentTaskRecord, event: RuntimeEvent) -> None:
        for key in ("sessionID", "session_id"):
            value = event.payload.get(key)
            if isinstance(value, str):
                if record.project_id is not None:
                    get_workspace_store().bind_session(value, record.project_id)
                record.session_id = value
                return

    async def _append(self, record: AgentTaskRecord, event: RuntimeEvent) -> None:
        async with self._lock:
            retained = AgentTaskEvent(
                sequence=len(record.events),
                type=event.type,
                payload=dict(event.payload),
                created_at=_now_iso(),
            )
            record.events.append(retained)
            record.updated_at = retained.created_at
            subscribers = tuple(self._subscribers.get(record.task_id, ()))
        for queue in subscribers:
            queue.put_nowait(retained)


_runtime: AgentRuntime | None = None
_manager: AgentTaskManager | None = None


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_runtime() -> AgentRuntime:
    executable = os.environ.get("WORKBENCH_OPENCODE_EXECUTABLE", "opencode")
    return OpenCodeRuntime(
        command=(executable,),
        default_workspace=_workspace_root(),
        domain_api_url=os.environ.get("WORKBENCH_API_URL", "http://127.0.0.1:8000"),
        model=os.environ.get("WORKBENCH_OPENCODE_MODEL"),
        attach_url=os.environ.get("WORKBENCH_OPENCODE_ATTACH"),
    )


def get_agent_manager() -> AgentTaskManager:
    global _runtime, _manager
    if _runtime is None:
        _runtime = _default_runtime()
    if _manager is None:
        _manager = AgentTaskManager(_runtime, workspace=_workspace_root())
    return _manager


def configure_agent_runtime(runtime: AgentRuntime) -> AgentTaskManager:
    """Replace the process runtime; integration tests inject deterministic fakes."""
    global _runtime, _manager
    _runtime = runtime
    _manager = AgentTaskManager(runtime, workspace=_workspace_root())
    return _manager


async def shutdown_agent_manager() -> None:
    """Stop live subprocesses without constructing a manager during shutdown."""
    global _runtime, _manager
    if _manager is not None:
        await _manager.shutdown()
    _manager = None
    _runtime = None


__all__ = [
    "AgentMode",
    "AgentTaskEvent",
    "AgentTaskManager",
    "AgentTaskNotFound",
    "AgentTaskRecord",
    "configure_agent_runtime",
    "get_agent_manager",
    "shutdown_agent_manager",
]
