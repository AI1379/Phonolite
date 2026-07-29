"""Audio DSP and pitch utilities, extracted from the Phonolite desktop app.

Pure numpy/scipy: no Qt, no audio I/O, no agent-host imports. This package
is the designated MIR / audio-analysis backend of the Music Agent
Workbench (see ``music_agent_workbench_design.md``, section 20 "External
Backends"), and is shared with the Phonolite app (``apps/phonolite``).
"""

__version__ = "0.1.0"
