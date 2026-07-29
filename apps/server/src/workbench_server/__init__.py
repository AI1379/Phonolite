"""FastAPI application layer for the Music Agent Workbench.

Thin layer only: validate requests, call into ``music_core``, and return
the unified result envelope (design doc section 8.4). Music-domain logic
belongs to ``music_core``, never here.
"""

__version__ = "0.1.0"
