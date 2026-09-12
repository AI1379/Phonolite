"""Replaceable agent runtime boundary for the Music Agent Workbench."""

from agent_runtime.models import AgentRuntime, JsonValue, RuntimeEvent, RuntimeTask
from agent_runtime.opencode import OpenCodeRuntime, OpenCodeRuntimeError

__version__ = "0.1.0"

__all__ = [
    "AgentRuntime",
    "JsonValue",
    "OpenCodeRuntime",
    "OpenCodeRuntimeError",
    "RuntimeEvent",
    "RuntimeTask",
]
