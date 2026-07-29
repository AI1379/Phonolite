"""Music domain core for the Music Agent Workbench.

Host-independent: no agent-runtime, web-framework, or UI imports allowed here.
The architectural source of truth is ``music_agent_workbench_design.md``
(repository root, Chinese); see sections 7 (domain core) and 19 (first
vertical slice).
"""

from music_core.ir import MeterEvent, NoteEvent, ScoreDocument, TempoEvent

__version__ = "0.1.0"

__all__ = [
    "MeterEvent",
    "NoteEvent",
    "ScoreDocument",
    "TempoEvent",
    "__version__",
]
