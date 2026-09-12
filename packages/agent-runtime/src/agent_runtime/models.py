"""Host-neutral task and event types for replaceable agent runtimes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Protocol, TypeAlias, runtime_checkable

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass(frozen=True)
class RuntimeTask:
    """One unit of work delegated to an external agent host."""

    task_id: str
    prompt: str
    workspace: str
    session_id: str | None = None
    permission_profile: str = "read_only"
    tool_profile: str = "workbench-analyze"
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeEvent:
    """A normalized streaming event emitted by an agent host."""

    type: str
    payload: Mapping[str, JsonValue]

    def to_dict(self) -> dict[str, JsonValue]:
        return {"type": self.type, "payload": dict(self.payload)}


@runtime_checkable
class AgentRuntime(Protocol):
    """Stable boundary used by the application instead of a host SDK."""

    def run(self, task: RuntimeTask) -> AsyncIterator[RuntimeEvent]:
        """Run a task and stream host events until a terminal event."""
        ...

    async def cancel(self, task_id: str) -> None:
        """Request cancellation of a running task."""
        ...

    def resume(self, session_id: str, prompt: str) -> AsyncIterator[RuntimeEvent]:
        """Continue an existing host session and stream its events."""
        ...


__all__ = ["AgentRuntime", "JsonValue", "RuntimeEvent", "RuntimeTask"]
