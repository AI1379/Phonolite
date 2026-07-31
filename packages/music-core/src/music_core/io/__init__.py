"""Import/export adapters between the Score IR and file formats.

Each adapter guarantees a tested round-trip for the IR subset it supports;
anything it cannot represent must be reported (never silently dropped).
"""
