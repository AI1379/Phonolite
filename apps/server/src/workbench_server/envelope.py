"""Unified tool-result envelope (design doc section 8.4).

Every Domain API response uses this shape so that the frontend and future
agent runtimes can handle results, warnings, and artifacts uniformly:

```json
{
  "ok": true,
  "result": {},
  "warnings": [],
  "artifacts": [],
  "provenance": {"tool": "inspect_score", "version": "0.1.0", "inputs": []}
}
```
"""

from __future__ import annotations

from typing import Any


def envelope(
    result: Any,
    *,
    tool: str,
    ok: bool = True,
    warnings: list[str] | None = None,
    artifacts: list[str] | None = None,
    inputs: list[str] | None = None,
    version: str = "0.1.0",
) -> dict[str, Any]:
    """Build the section-8.4 envelope around a tool result."""
    return {
        "ok": ok,
        "result": result,
        "warnings": warnings or [],
        "artifacts": artifacts or [],
        "provenance": {
            "tool": tool,
            "version": version,
            "inputs": inputs or [],
        },
    }
